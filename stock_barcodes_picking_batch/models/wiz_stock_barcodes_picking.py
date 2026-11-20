# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from datetime import datetime

from odoo import _, fields, models
from odoo.tools.float_utils import float_compare

BATCH_ACTIVE_STATES = ("draft", "in_progress")


class WizStockBarcodesPicking(models.TransientModel):
    _inherit = "wiz.stock.barcodes.picking"

    batch_id = fields.Many2one(
        comodel_name="stock.picking.batch",
        string="Batch Transfer",
        index=True,
        ondelete="cascade",
        help="When set, the scan page works on the whole batch: every "
             "picking of the batch is displayed on one page and each scan "
             "is routed to the first picking that needs the product.",
    )

    # ------------------------------------------------------------------
    # batch helpers
    # ------------------------------------------------------------------

    def _batch_pickings(self):
        """Pickings of the batch that can still be picked, in picking order."""
        self.ensure_one()
        pickings = self.batch_id.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )
        return pickings.sorted(
            lambda picking: (picking.scheduled_date or datetime.max, picking.id)
        )

    def _batch_picked_qty(self, move):
        return sum(
            line.quantity for line in move.move_line_ids if line.picked
        )

    def _batch_move_remaining(self, move):
        demand = move.product_uom_qty
        if not demand:
            demand = sum(move.move_line_ids.mapped("quantity"))
        return max(demand - self._batch_picked_qty(move), 0.0)

    def _batch_picking_for_product(self, product):
        """First picking of the batch still needing ``product``."""
        fallback = self.env["stock.picking"]
        for picking in self._batch_pickings():
            moves = picking.move_ids.filtered(
                lambda move: move.product_id == product
                and move.state not in ("done", "cancel")
            )
            if not moves:
                continue
            if not fallback:
                fallback = picking
            if any(self._batch_move_remaining(move) > 0 for move in moves):
                return picking
        return fallback

    def _batch_picking_for_lot(self, lot):
        """First picking of the batch with this lot/serial still to pick."""
        for picking in self._batch_pickings():
            lines = picking.move_line_ids.filtered(
                lambda line: line.lot_id == lot and not line.picked
            )
            if lines:
                return picking
        return self._batch_picking_for_product(lot.product_id)

    def _batch_picking_for_package(self, package):
        for picking in self._batch_pickings():
            lines = picking.move_line_ids.filtered(
                lambda line: line.package_id == package
                or line.result_package_id == package
            )
            if lines:
                return picking
        return self.env["stock.picking"]

    def _batch_target_picking(self, barcode):
        """Resolve the picking that should receive ``barcode``.

        Returns an empty recordset when the barcode is not a product /
        lot / package (locations, transfer names, ...): those scans keep
        working on the current picking.
        """
        if not barcode:
            return self.env["stock.picking"]
        products = self.env["product.product"].search(
            [("barcode", "=", barcode), ("type", "=", "consu")]
        )
        if len(products) == 1:
            return self._batch_picking_for_product(products)
        lots = self.env["stock.lot"].search(
            [
                ("name", "=", barcode),
                ("company_id", "in", [self.company_id.id, False]),
            ]
        )
        if len(lots) == 1:
            return self._batch_picking_for_lot(lots)
        packages = self.env["stock.quant.package"].search(
            [("name", "=", barcode)], limit=2
        )
        if len(packages) == 1:
            return self._batch_picking_for_package(packages)
        return self.env["stock.picking"]

    def _batch_flow_in_progress(self):
        """True while a multi-step scan (product -> lot -> qty) is open.

        In that case the target picking must NOT be recomputed: the next
        scan belongs to the same document.
        """
        self.ensure_one()
        if (
            self.visible_switch_selector
            or self.visible_force_add
            or self.cross_order_pending
            or self.pending_add
        ):
            return True
        if (self.scan_mode or "default") not in ("default",):
            return True
        return self.step > self._step_index("product")

    def _batch_switch_for_move(self, move_id):
        if not self.batch_id or not move_id:
            return
        move = self.env["stock.move"].browse(int(move_id)).exists()
        picking = move.picking_id
        if (
            picking
            and picking != self.picking_id
            and picking in self.batch_id.picking_ids
            and picking.state not in ("done", "cancel")
        ):
            self._switch_picking(picking)

    def _batch_switch_for_line(self, line_id):
        if not self.batch_id or not line_id:
            return
        line = self.env["stock.move.line"].browse(int(line_id)).exists()
        if line:
            self._batch_switch_for_move(line.move_id.id)

    def _batch_switch_for_package(self, package_id):
        if not self.batch_id or not package_id:
            return
        package = self.env["stock.quant.package"].browse(int(package_id)).exists()
        if not package:
            return
        picking = self._batch_picking_for_package(package)
        if (
            picking
            and picking != self.picking_id
            and picking.state not in ("done", "cancel")
        ):
            self._switch_picking(picking)

    # ------------------------------------------------------------------
    # batch state
    # ------------------------------------------------------------------

    def _batch_picking_state(self, picking):
        """Run the single-picking state snapshot for one picking."""
        original = self.picking_id
        if picking != original:
            self.picking_id = picking
            self.flush_recordset(["picking_id"])
        try:
            return super().get_scan_state()
        finally:
            if picking != original:
                self.picking_id = original
                self.flush_recordset(["picking_id"])

    def _get_picking_action_menu_items(self):
        """Batch mode: the cog menu drives the batch form, not the picking."""
        if self.batch_id:
            return self._batch_action_menu_items()
        return super()._get_picking_action_menu_items()

    def _batch_action_menu_items(self):
        """Toolbar (actions + print) of the batch form, for the cog menu."""
        toolbar = {}
        view = self.env.ref(
            "stock_picking_batch.stock_picking_batch_form",
            raise_if_not_found=False,
        )
        if view:
            try:
                result = self.env["stock.picking.batch"].get_views(
                    [(view.id, "form")], {"toolbar": True}
                )
                toolbar = result["views"]["form"].get("toolbar", {})
            except Exception:
                toolbar = {}
        return {
            "action": toolbar.get("action", []),
            "print": toolbar.get("print", []),
        }

    def get_scan_state(self):
        state = super().get_scan_state()
        if not self.batch_id:
            return state
        current = self.picking_id
        pickings = self._batch_pickings()
        ordered = ([current] if current in pickings else []) + [
            picking for picking in pickings if picking != current
        ]
        moves = []
        rows = []
        total_demand = 0.0
        total_done = 0.0
        for picking in ordered:
            snapshot = self._batch_picking_state(picking)
            for move in snapshot["move_ids"]:
                move["picking_id"] = picking.id
                move["picking_name"] = picking.name
                move["picking_state"] = picking.state
            for row in snapshot["rows"]:
                row["picking_id"] = picking.id
                row["picking_name"] = picking.name
                row["picking_state"] = picking.state
            moves.extend(snapshot["move_ids"])
            rows.extend(snapshot["rows"])
            total_demand += snapshot["total_demand"]
            total_done += snapshot["total_done"]
        # Restore the current picking context for the interactive fields.
        if self.picking_id != current:
            self.picking_id = current
            self.flush_recordset(["picking_id"])
        state["move_ids"] = moves
        state["rows"] = rows
        state["total_demand"] = total_demand
        state["total_done"] = total_done
        state["batch_id"] = self.batch_id.id
        state["batch_name"] = self.batch_id.name
        state["batch_state"] = self.batch_id.state
        state["batch_picking_count"] = len(ordered)
        state["picking_name"] = self.batch_id.name
        state["action_menu_items"] = self._batch_action_menu_items()
        return state

    # ------------------------------------------------------------------
    # scan routing
    # ------------------------------------------------------------------

    def _get_step_message(self):
        message = super()._get_step_message()
        if self.batch_id and self.picking_id and self.picking_id.name:
            message = message.replace(self.picking_id.name, self.batch_id.name)
        return message

    def _process_barcode(self, barcode):
        if self.batch_id and barcode and not self._batch_flow_in_progress():
            target = self._batch_target_picking(barcode.strip())
            if target and target != self.picking_id:
                self._switch_picking(target)
        return super()._process_barcode(barcode)

    def _switch_picking(self, new_picking):
        if self.batch_id:
            if (
                new_picking not in self.batch_id.picking_ids
                or new_picking.state in ("done", "cancel")
            ):
                self._set_message(
                    "error",
                    self.env._(
                        "Transfer %(name)s is not available in this batch.",
                        name=new_picking.name,
                    ),
                )
                return
        return super()._switch_picking(new_picking)

    def _scan_picking(self, barcode):
        if not self.batch_id:
            return super()._scan_picking(barcode)
        barcode = (barcode or "").strip()
        if not barcode:
            return False
        if barcode == self.batch_id.name:
            self._set_message(
                "info", self.env._("Working on batch %s", self.batch_id.name)
            )
            return True
        pickings = self.batch_id.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )
        candidates = pickings.filtered(lambda picking: picking.name == barcode)
        if not candidates:
            candidates = pickings.filtered(
                lambda picking: barcode.lower() in picking.name.lower()
            )
        if not candidates:
            return False
        if len(candidates) > 1:
            self.pending_switch_picking_ids = [(6, 0, candidates.ids)]
            self.visible_switch_selector = True
            self._set_message(
                "more_match",
                self.env._("Multiple transfers match this barcode."),
            )
            return True
        target = candidates[0]
        if target == self.picking_id:
            self._set_message(
                "info",
                self.env._("Already working on transfer %(name)s.", name=target.name),
            )
            return True
        self._switch_picking(target)
        return True

    # ------------------------------------------------------------------
    # row actions routed to the row's own picking
    # ------------------------------------------------------------------

    def set_active_move(self, move_id):
        self._batch_switch_for_move(move_id)
        return super().set_active_move(move_id)

    def action_add_move_quantity(self, move_id, quantity=None, package_id=None):
        self._batch_switch_for_move(move_id)
        return super().action_add_move_quantity(move_id, quantity, package_id)

    def action_edit_package_qty(self, move_id, package_id, qty, force=False):
        self._batch_switch_for_move(move_id)
        return super().action_edit_package_qty(move_id, package_id, qty, force)

    def action_pick_reserved_lot(self, move_id, lot_id, quantity=1.0):
        self._batch_switch_for_move(move_id)
        return super().action_pick_reserved_lot(move_id, lot_id, quantity)

    def action_edit_move_line_qty(self, line_id, qty, force=False):
        self._batch_switch_for_line(line_id)
        return super().action_edit_move_line_qty(line_id, qty, force)

    def action_edit_move_line(
        self,
        line_id,
        qty=None,
        lot_name=None,
        package_name=None,
        result_package_name=None,
    ):
        self._batch_switch_for_line(line_id)
        return super().action_edit_move_line(
            line_id, qty, lot_name, package_name, result_package_name
        )

    def action_remove_move_lot(self, line_id):
        self._batch_switch_for_line(line_id)
        return super().action_remove_move_lot(line_id)

    def action_remove_move_qty(self, row_key):
        move_id = (row_key or "").split("_")[0]
        if move_id.isdigit():
            self._batch_switch_for_move(int(move_id))
        return super().action_remove_move_qty(row_key)

    def action_unclaim_unit(self, product_id, package_id=False):
        self._batch_switch_for_package(package_id)
        return super().action_unclaim_unit(product_id, package_id)

    def action_split_unit(self, product_id, package_id=False):
        self._batch_switch_for_package(package_id)
        return super().action_split_unit(product_id, package_id)

    def action_remove_package(self, package_id):
        self._batch_switch_for_package(package_id)
        return super().action_remove_package(package_id)

    def action_undo_package_scan(self, package_id):
        self._batch_switch_for_package(package_id)
        return super().action_undo_package_scan(package_id)

    def action_unpack_package(self, package_id, move_id=False):
        self._batch_switch_for_package(package_id)
        return super().action_unpack_package(package_id, move_id)

    def action_select_existing_package(self, package_id):
        self._batch_switch_for_package(package_id)
        return super().action_select_existing_package(package_id)

    def action_edit_package_name(self, package_id, new_name):
        self._batch_switch_for_package(package_id)
        return super().action_edit_package_name(package_id, new_name)

    # ------------------------------------------------------------------
    # batch validation
    # ------------------------------------------------------------------

    def switch_to_backorder_if_any(self):
        if self.batch_id:
            # The batch is validated as a whole; never jump to a backorder.
            return False
        return super().switch_to_backorder_if_any()

    def action_validate_picking(self):
        if not self.batch_id:
            return super().action_validate_picking()
        if not self._check_selector_resolved():
            return False
        batch = self.batch_id
        if batch.state not in BATCH_ACTIVE_STATES:
            self._set_message(
                "error", self.env._("The batch transfer can no longer be validated.")
            )
            return False
        pickings = self._batch_pickings()
        if not pickings:
            self._set_message(
                "error", self.env._("This batch has no transfer left to pick.")
            )
            return False
        for picking in pickings:
            if self._lines_need_pack(picking):
                unpacked = picking.move_line_ids.filtered(
                    lambda line: line.picked and not line.result_package_id
                )
                if unpacked:
                    self._set_message(
                        "error",
                        self.env._(
                            "Transfer %(name)s still has picked products "
                            "outside a package. Put them in a package before "
                            "validating the batch.",
                            name=picking.name,
                        ),
                    )
                    return False
        incomplete = []
        for picking in pickings:
            for move in picking.move_ids.filtered(
                lambda move: move.state not in ("done", "cancel")
            ):
                demand = move.product_uom_qty
                if not demand:
                    demand = sum(move.move_line_ids.mapped("quantity"))
                done = self._batch_picked_qty(move)
                if (
                    float_compare(
                        done,
                        demand,
                        precision_rounding=move.product_uom.rounding,
                    )
                    < 0
                ):
                    incomplete.append(picking.name)
                    break
        if incomplete:
            self._set_message(
                "error",
                self.env._(
                    "All transfers must be fully picked before validating "
                    "the batch. Still incomplete: %(names)s",
                    names=", ".join(incomplete),
                ),
            )
            return False
        for picking in pickings:
            self._normalize_zero_demand(picking)
        result = batch.action_done()
        self._set_message(
            "success", self.env._("Batch transfer validated.")
        )
        if isinstance(result, dict):
            result.setdefault("views", [(False, "form")])
            return result
        return True
