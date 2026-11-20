# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models

from odoo.tools.float_utils import float_compare, float_is_zero


class WizStockBarcodesPicking(models.TransientModel):
    _name = "wiz.stock.barcodes.picking"
    _inherit = "barcodes.barcode_events_mixin"
    _description = "Wizard to read barcode on pickings"
    _transient_max_hours = 48

    # --- Picking context ---
    # NB: NOT field-level readonly. Readonly fields are dropped from the
    # client save payload, so a hardware/manual scan landing on a *new*
    # onchange RPC would browse a record with picking_id=False and every
    # cross-request scan step would fall through ("Barcode not found").
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
    )
    picking_state = fields.Selection(related="picking_id.state")
    picking_type_code = fields.Selection(related="picking_id.picking_type_code")
    picking_location_id = fields.Many2one(
        comodel_name="stock.location",
        related="picking_id.location_id",
        string="Picking Source Location",
        help="Static: the picking's own source location, bound when "
             "picking_id is set. Never overwritten by scanning.",
    )
    picking_location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        related="picking_id.location_dest_id",
        string="Destination Location",
        help="Static: the picking's destination location.",
    )
    company_id = fields.Many2one(related="picking_id.company_id")

    # --- Picking-type barcode configuration ---
    barcode_scan_source_location = fields.Boolean(
        related="picking_id.picking_type_id.barcode_scan_source_location",
        string="Scan Source Location",
        help="Whether the operator must scan the source location barcode. "
             "When False, the picking's default source location is used.",
    )
    barcode_scan_dest_location = fields.Boolean(
        related="picking_id.picking_type_id.barcode_scan_dest_location",
        string="Scan Destination Location",
        help="Whether the operator must scan the destination location "
             "barcode. When False, the picking's default destination "
             "location is used.",
    )

    # --- Scanned values ---
    barcode = fields.Char()
    res_model_id = fields.Many2one(comodel_name="ir.model", index=True)
    res_id = fields.Integer(index=True)
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Scanned Source Location",
        help="Dynamic: the source location scanned by the operator. "
             "Overrides picking_location_id for the current scan context. "
             "Defaulted to picking_location_id on picking switch.",
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Scanned Destination Location",
        help="Dynamic: the destination location scanned by the operator. "
             "Only used when the picking type requires destination "
             "location scanning. Otherwise picking_location_dest_id "
             "is used.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
    )
    product_uom_id = fields.Many2one(comodel_name="uom.uom", string="UoM")
    product_tracking = fields.Selection(related="product_id.tracking", readonly=True)
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot/Serial")
    lot_name = fields.Char()
    product_qty = fields.Float(
        string="Quantity", digits="Product Unit of Measure"
    )
    manual_entry = fields.Boolean(
        string="Manual", help="Manual entry mode",
        default=False,
    )

    # --- Display fields ---
    message_type = fields.Selection(
        [
            ("info", "Info"),
            ("not_found", "Not found"),
            ("more_match", "Multiple matches"),
            ("success", "Success"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
        readonly=True,
    )
    message = fields.Char(readonly=True)
    step = fields.Integer(default=0)
    visible_force_done = fields.Boolean()
    visible_force_add = fields.Boolean(
        string="Force Add",
        help="Show the 'Force Add' button to move a product not in the picking",
    )
    allow_new_products = fields.Boolean(
        help="Created from the workbench '+' action: the picking starts empty, "
             "so every scanned product (tracked or not) may create a new move.",
    )
    cross_order_pending = fields.Boolean(
        help="A serial scan was blocked because another transfer still "
             "reserves it; the operator may confirm to pick it anyway.",
    )
    scan_mode = fields.Selection(
        selection=[
            ("default", "Pick"),
            ("pack", "Pack into package"),
            ("split_scan", "Remove package by scanning"),
            ("unclaim_scan", "Unclaim by scanning"),
        ],
        default="default",
        help="What a scan means right now. 'default' picks products (a "
             "package barcode picks the whole package), 'pack' binds scanned "
             "products to a package, 'split_scan' removes the package from "
             "the scanned product/package, 'unclaim_scan' sets the scanned "
             "lines back to not picked. Empty (NULL) is treated as "
             "'default': packages are optional and transfers without any "
             "package must keep working.",
    )
    package_scan_intent = fields.Selection(
        selection=[
            ("take", "Whole package"),
            ("pack", "Pack into package"),
        ],
        compute="_compute_package_scan_intent",
        help="Compatibility mirror of scan_mode kept for the pre-v4 client "
             "action: 'pack' while scan_mode is 'pack', 'take' otherwise.",
    )
    qty_available = fields.Float(
        string="Available", digits="Product Unit of Measure", readonly=True,
    )
    total_demand = fields.Float(
        string="Demand", digits="Product Unit of Measure",
        compute="_compute_totals",
    )
    total_done = fields.Float(
        string="Done", digits="Product Unit of Measure",
        compute="_compute_totals",
    )

    # --- Move checklist (picking.move_ids) ---
    move_ids = fields.One2many(
        related="picking_id.move_ids",
        string="Stock Moves",
        readonly=True,
    )

    # --- Click-to-select target move ---
    active_move_id = fields.Many2one(
        comodel_name="stock.move",
        help="Operator-selected target move. When set, scanning a "
             "serial/lot narrows the lot lookup to this move's product "
             "first, so cross-product SN collisions resolve automatically. "
             "Cleared on picking switch or scanning a different product.",
    )

    # --- Unclaim by scan: package chooser ---
    unclaim_product_id = fields.Many2one(
        comodel_name="product.product",
        help="Quantity-tracked product whose picked units are spread over "
             "several packages: the operator chooses the package to unclaim.",
    )
    unclaim_choices = fields.Json(
        help="Package choices shown by the unclaim dialog: "
             "[{package_id, package_name, quantity}, ...]",
    )
    # --- Over-demand row add: pending confirmation ---
    pending_add = fields.Json(
        help="Row quantity add blocked by the 'warn' over-pick policy: "
             "{move_id, qty, package_id}. The footer force button applies it.",
    )

    # --- Scan-first picking switching ---
    pending_switch_picking_ids = fields.Many2many(
        comodel_name="stock.picking",
        string="Candidate Pickings",
        help="Pickings matching an ambiguous scan; the operator picks one "
             "to switch to.",
    )
    visible_switch_selector = fields.Boolean(
        string="Show Picking Selector",
        help="Display the ambiguous-picking selection list.",
    )
    scan_progress_stash = fields.Json(
        string="Stashed Scan Progress",
    )

    # --- Scan steps ---
    def _get_scan_rows_v4(self):
        """Row model for the v4 client action: one row per move.

        Each lot carries its own package chip (source > destination),
        which is what the new design shows under the lot selector.
        Kept alongside move_ids so the previous client action still
        renders while the frontend is migrated.
        """
        self.ensure_one()
        picking = self.picking_id
        if not picking:
            return []
        optional_scan = (
            picking.picking_type_id.barcode_lot_scan_policy == "optional"
        )
        rows = []
        for move in picking.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        ):
            lines = move.move_line_ids.sorted(lambda l: l.id)
            if not lines and not move.product_uom_qty:
                # Placeholder move with neither demand nor lines: nothing
                # to show or scan, skip it.
                continue
            picked_lines = lines.filtered("picked")
            demand = move.product_uom_qty
            if not demand:
                demand = sum(lines.mapped("quantity"))
            if move.product_id.tracking == "none":
                # Like the official barcode app: each destination package
                # gets its own product row, plus a row for the unpacked
                # remainder (still to pick / picked outside a package).
                # The demand is split across those rows and always sums
                # back to the document demand: packages are served in
                # packing order with what they hold, the last one is
                # capped by the demand left, and anything above that is
                # an over-pick shown on the picked side only (10 units,
                # 4 packed -> 4/4 and 0/6; 13 + 14 packed -> 13/13 and
                # 14/7, never 14/14).
                package_groups = {}
                for line in picked_lines.filtered("result_package_id"):
                    pkg_id = line.result_package_id.id
                    package_groups.setdefault(
                        pkg_id, self.env["stock.move.line"]
                    )
                    package_groups[pkg_id] |= line
                if package_groups:
                    remaining_demand = demand
                    allocated = []
                    for pkg_id, pkg_lines in package_groups.items():
                        pkg_picked = sum(pkg_lines.mapped("quantity"))
                        row_demand = min(
                            pkg_picked, max(0.0, remaining_demand)
                        )
                        remaining_demand -= row_demand
                        allocated.append((pkg_id, pkg_lines, row_demand))
                    remainder_lines = lines.filtered(
                        lambda line: not line.result_package_id
                    )
                    remainder_picked = sum(
                        remainder_lines.filtered("picked").mapped("quantity")
                    )
                    remainder_demand = max(0.0, remaining_demand)
                    if remainder_demand or remainder_picked:
                        # Unpacked remainder first, like the official row
                        # order (original line, then the packed lines).
                        rows.append(self._build_scan_row(
                            move,
                            remainder_lines,
                            remainder_demand,
                            optional_scan,
                            package_id=False,
                            row_key=f"{move.id}_0",
                        ))
                    for pkg_id, pkg_lines, row_demand in allocated:
                        rows.append(self._build_scan_row(
                            move,
                            pkg_lines,
                            row_demand,
                            optional_scan,
                            package_id=pkg_id,
                            row_key=f"{move.id}_{pkg_id}",
                        ))
                    continue
            rows.append(self._build_scan_row(
                move,
                lines,
                demand,
                optional_scan,
            ))
        return rows

    def _build_scan_row(
        self,
        move,
        lines,
        demand,
        optional_scan,
        package_id=False,
        row_key=None,
    ):
        """Build one product row for the v4 client action.

        ``lines`` is the subset this row represents: all move lines for a
        regular row, or one destination-package group / the unpacked
        remainder when a non-tracked move is split across packages.
        ``demand`` is the demand of this row (the move demand is split
        across the package rows and the remainder row).
        """
        tracking = move.product_id.tracking
        lots_by_key = {}
        for line in lines:
            if tracking != "none" and not line.lot_id and not line.picked:
                # Reservation placeholder of a tracked product: the
                # quantity is reserved but no lot/serial is assigned
                # yet. It is not actionable in the scan view (there is
                # no lot to pick, edit or show) and used to render a
                # dead "未分配批次 / +1" row in the lot dropdown.
                continue
            key = (line.lot_id.id or False, line.picked)
            entry = lots_by_key.get(key)
            if not entry:
                entry = {
                    "id": line.lot_id.id or False,
                    "name": line.lot_id.name or line.lot_name or "",
                    "picked": line.picked,
                    "quantity": 0.0,
                    "reserved_quantity": 0.0,
                    "package_from": line.package_id.name or "",
                    "package_to": line.result_package_id.name or "",
                    "demand_qty": 0.0,
                    "show_add": optional_scan and not line.picked,
                    "line_ids": [],
                }
                lots_by_key[key] = entry
            if line.picked:
                entry["quantity"] += line.quantity
            else:
                entry["reserved_quantity"] += line.quantity
            entry["demand_qty"] = (
                entry["quantity"] + entry["reserved_quantity"]
            )
            entry["line_ids"].append(line.id)
            if not entry["package_from"] and line.package_id:
                entry["package_from"] = line.package_id.name
            if not entry["package_to"] and line.result_package_id:
                entry["package_to"] = line.result_package_id.name
        return {
            "row_key": row_key or str(move.id),
            "move_id": move.id,
            "package_id": package_id or False,
            "product_id": move.product_id.id,
            "product_name": move.product_id.display_name,
            "tracking": tracking,
            "location_name": move.location_id.display_name,
            "location_dest_name": move.location_dest_id.display_name,
            "demand_qty": demand,
            "picked_qty": sum(
                line.quantity for line in lines if line.picked
            ),
            "uom_name": move.product_uom.name,
            "active": self.active_move_id.id == move.id,
            "editable": True,
            "lots": list(lots_by_key.values()),
        }

    def _get_scan_steps(self):
        """Current picking type's ordered scan steps.

        Steps are built from the picking type's barcode configuration:
          - ``location``      included only if barcode_scan_source_location
          - ``dest_location`` included only if barcode_scan_dest_location
          - ``product``       always
          - ``lot``           always (skipped for non-tracked products
                              inside _scan_product, which jumps to qty)
          - ``qty``           always

        Both location steps (when enabled) come BEFORE product so that
        move lines are created with the correct source/destination
        locations from the first pick.

        When a step is absent from this list, _step_index(key) asserts;
        callers must guard on the config flags before referencing a
        conditional step.
        """
        self.ensure_one()
        steps = []
        if self.barcode_scan_source_location:
            steps.append("location")
        if self.barcode_scan_dest_location:
            steps.append("dest_location")
        steps.extend(["product", "lot", "qty"])
        return steps

    # --- Message state machine ---
    def _set_message(self, message_type, message):
        self.message_type = message_type
        self.message = message

    def _get_step_message(self):
        """Context-aware scan instruction for the current step.

        Always states WHAT to scan next and for which product/picking, so
        the text stays meaningful after a progress restore
        (_restore_progress re-runs _set_message_step and the banner
        reflects the restored step automatically).
        """
        self.ensure_one()
        target_product = self.product_id or (
            self.active_move_id.product_id if self.active_move_id else False
        )
        steps = self._get_scan_steps()
        if self.step < 0 or self.step >= len(steps):
            return ""
        step_key = steps[self.step]
        if step_key == "location":
            return self.env._("Scan the source location of transfer %s", self.picking_id.name or "")
        if step_key == "product":
            return self.env._("Please scan a product of transfer %s", self.picking_id.name or "")
        if step_key == "lot":
            if not target_product:
                return self.env._("Scan a product barcode first")
            return self.env._("Scan the lot/serial of %s", target_product.name)
        if step_key == "qty":
            if not target_product:
                return self.env._("Scan a product barcode first")
            return self.env._("Enter the quantity for %s", target_product.name)
        if step_key == "dest_location":
            return self.env._("Scan the destination location of transfer %s", self.picking_id.name or "")
        return ""

    def _set_message_step(self):
        # Dynamic instruction for the banner (driven by the scan-flow
        # `step` state machine).
        self._set_message("info", self._get_step_message())

    # --- Totals ---
    @api.depends("picking_id")
    def _compute_totals(self):
        """Picking-wide progress: total demand vs picked quantity.

        Computed over ALL moves of the picking (not just the currently
        scanned product) so the progress bar stays meaningful after a
        serial auto-confirm clears product_id. Only picked move lines
        count toward ``total_done`` — reserved-but-unpicked lines do
        not, otherwise an assigned picking would show 100% before any
        scan.
        """
        for rec in self:
            rec.total_demand = 0.0
            rec.total_done = 0.0
            if not rec.picking_id:
                continue
            moves = rec.picking_id.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            )
            demand = sum(m.product_uom_qty for m in moves)
            if not demand:
                # Package-driven transfers carry the quantity on the move
                # lines (product_uom_qty stays 0), otherwise the progress
                # would read 0/0 and the operator sees no target.
                demand = sum(moves.move_line_ids.mapped("quantity"))
            rec.total_demand = demand
            # One read of the picking's lines (instead of one per move)
            # keeps this cheap on large transfers.
            active_move_ids = set(moves.ids)
            rec.total_done = sum(
                line.quantity
                for line in rec.picking_id.move_line_ids
                if line.picked and line.move_id.id in active_move_ids
            )

    # --- Default values ---
    def _set_default_values(self):
        """Set the wizard to a clean initial state for the current picking.

        Called on picking switch and after a successful move line
        confirmation to advance the step machine.

        The starting step depends on the picking type's barcode
        configuration:
          - source location scanning ON  → start at "location"
          - source location scanning OFF → start at "product" and use
            the picking's default source location automatically.
        """
        self.ensure_one()
        if not self.picking_id:
            self.step = 0
            return
        self.scan_mode = self._default_scan_mode()
        if self.barcode_scan_source_location:
            self.step = self._step_index("location")
            # location_id stays False — the operator MUST scan the source
            # location. action_confirm's "not location_id → error" check
            # enforces this.
            self.location_id = False
        else:
            # Skip the source-location step: use the picking's default
            # source location directly.
            self.location_id = self.picking_location_id
        if not self.barcode_scan_dest_location:
            # Use the picking's default destination location.
            self.location_dest_id = self.picking_location_dest_id
        # Step lands on the first required location step, or "product"
        # when both location scans are disabled.
        self.step = 0
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self._set_message_step()

    # --- Picking switch with stash/restore ---
    def _stash_current_progress(self):
        """Snapshot the uncommitted scan state of the current picking.

        Restored (and consumed) by ``_restore_progress`` when the operator
        switches back. Only pickings with an in-progress scan (product or
        lot already scanned) are stashed.
        """
        self.ensure_one()
        picking = self.picking_id
        if not picking or not (self.product_id or self.lot_id):
            return
        stash = dict(self.scan_progress_stash or {})
        stash[str(picking.id)] = {
            "product_id": self.product_id.id if self.product_id else False,
            "product_uom_id": (
                self.product_uom_id.id if self.product_uom_id else False
            ),
            "lot_id": self.lot_id.id if self.lot_id else False,
            "lot_name": self.lot_name,
            "product_qty": self.product_qty,
            "location_id": self.location_id.id if self.location_id else False,
            "location_dest_id": (
                self.location_dest_id.id if self.location_dest_id else False
            ),
            "active_move_id": (
                self.active_move_id.id if self.active_move_id else False
            ),
            "step": self.step,
            "visible_force_done": self.visible_force_done,
            "visible_force_add": self.visible_force_add,
        }
        self.scan_progress_stash = stash

    def _restore_progress(self, picking):
        """Restore uncommitted scan state stashed for ``picking``.

        The stash entry is consumed (deleted) on restore. Returns True when
        a snapshot was restored, False when there was none.

        For picking, step 0 = location is a valid step, so we do NOT coerce
        it (unlike mrp's step-0-is-finished-lot pattern).
        """
        self.ensure_one()
        stash = dict(self.scan_progress_stash or {})
        snapshot = stash.pop(str(picking.id), None)
        if not snapshot:
            return False
        self.scan_progress_stash = stash
        self.product_id = snapshot.get("product_id") or False
        self.product_uom_id = snapshot.get("product_uom_id") or False
        self.lot_id = snapshot.get("lot_id") or False
        self.lot_name = snapshot.get("lot_name") or False
        self.product_qty = snapshot.get("product_qty") or 0.0
        self.location_id = snapshot.get("location_id") or False
        self.location_dest_id = snapshot.get("location_dest_id") or False
        self.active_move_id = snapshot.get("active_move_id") or False
        self.visible_force_done = bool(snapshot.get("visible_force_done"))
        self.visible_force_add = bool(snapshot.get("visible_force_add"))
        # step 0 may be "location" or "product" depending on the picking
        # type config — do not coerce. Fall back to the first step of the
        # current picking type's step list (safe even when the source
        # location step is disabled).
        step = snapshot.get("step")
        self.step = step if step is not None else 0
        if self.product_id:
            self._compute_qty_available()
        self._set_message_step()
        return True

    def _switch_picking(self, new_picking):
        """Switch the wizard to ``new_picking``, resetting scan context.

        Call order (enforced here, not by callers):
          1. ``_stash_current_progress`` — snapshot the OLD picking's
             in-progress scan before we overwrite any state.
          2. reset all scan fields to defaults.
          3. ``_restore_progress(new_picking)`` — restore the NEW
             picking's stashed scan if any; otherwise fall back to
             ``_set_default_values`` (fresh start from location step).

        location_id is reset to False during step 2 and may be restored
        by ``_restore_progress`` (if the operator had already scanned the
        source location for this picking). ``_set_default_values`` does
        NOT set location_id, so a fresh picking starts at the location
        step and the operator must scan.
        """
        self.ensure_one()
        # 1. Stash the old picking's progress (must run BEFORE any field
        #    is overwritten so the snapshot reflects the live state).
        if self.picking_id and self.picking_id != new_picking:
            self._stash_current_progress()
        # 2. Reset scan context
        self.picking_id = new_picking
        self.product_id = False
        self.product_uom_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.location_id = False
        self.location_dest_id = False
        self.active_move_id = False
        self.visible_force_done = False
        self.visible_force_add = False
        self.scan_mode = self._default_scan_mode()
        self.cross_order_pending = False
        self.barcode = False
        self.res_model_id = self.env.ref("stock.model_stock_picking").id
        self.res_id = new_picking.id
        self.pending_switch_picking_ids = [(5, 0, 0)]
        self.visible_switch_selector = False
        # 3. Restore stashed progress for the new picking, or start fresh
        if not self._restore_progress(new_picking):
            self._set_default_values()
        self._set_message(
            "info",
            self.env._("Switched to transfer %(picking)s. %(next)s", **{"picking": new_picking.name, "next": self.message}),
        )

    def select_picking_candidate(self, picking_id):
        """User picks one of the candidate pickings from the selector.

        Validates the picked id is among the pending candidates, then
        switches to it (which closes the selector and clears candidates).
        """
        self.ensure_one()
        candidates = self.pending_switch_picking_ids
        picked = candidates.filtered(lambda p: p.id == picking_id)
        if not picked:
            self._set_message(
                "error",
                self.env._("Selected transfer is not in the candidate list"),
            )
            return False
        self._switch_picking(picked)
        return True

    # --- State snapshot for the OWL client ---
    def get_scan_state(self):
        """JSON-serializable snapshot of the wizard state for the OWL
        client action to render.
        """
        self.ensure_one()
        # ★ 强制刷新 related 字段缓存 — wizard.move_ids 是 picking.move_ids
        # 的 related，新增/删除 move 后必须 invalidate 才能看到最新值。
        self.invalidate_recordset()
        picking = self.picking_id
        picking.invalidate_recordset()
        # Step labels are built here (not as a class attribute) so _() is
        # evaluated at request time under the correct lang context. Unknown
        # keys fall back to the raw key string (no default label) so a
        # missing mapping is visible in the UI instead of silently wrong.
        step_labels = {
            "location": self.env._("库位"),
            "product": self.env._("产品"),
            "lot": self.env._("批次"),
            "qty": self.env._("数量"),
            "dest_location": self.env._("目的库位"),
        }
        scan_steps = [
            {"key": k, "label": step_labels.get(k, k)}
            for k in self._get_scan_steps()
        ]
        lot_scan_policy = self._get_lot_scan_policy()
        show_reserved = bool(
            picking.picking_type_id.barcode_show_reserved_sns
            or lot_scan_policy == "optional"
        )
        # Read every move line (and the names it references) ONCE. Reading
        # them per move gave each move its own prefetch group, so a N-move
        # picking paid ~N extra SELECTs per scan (10 moves -> 10 separate
        # stock_lot queries). Warming the cache here keeps the loop below
        # query-free and also benefits _compute_totals.
        # Exclude moves that are done or cancelled.
        # NOTE: we intentionally do NOT filter out confirmed moves with no
        # move_line_ids yet — the scan UI lets the operator pre-add a product
        # before reserving stock, and we want those to show up so they can be
        # scanned (consuming raw material / creating demand).
        active_moves = self.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
        all_lines = picking.move_line_ids
        lot_name_by_id = {lot.id: lot.name for lot in all_lines.lot_id}
        package_name_by_id = {
            pkg.id: pkg.name for pkg in all_lines.result_package_id
        }
        location_name_by_id = {
            location.id: location.display_name or ""
            for location in all_lines.location_id
        }
        location_dest_name_by_id = {
            location.id: location.display_name or ""
            for location in all_lines.location_dest_id
        }
        # Unit of measure is only meaningful when the UoM feature is on;
        # otherwise every product is a plain count and the card hides the
        # unit next to the picked quantity (design 20 rule 4).
        # The default counting unit (Units/单位/件) carries no information,
        # so it is hidden too — only real units (kg, m, Pack of 6…) show.
        uom_enabled = self.env.user.has_group("uom.group_uom")
        default_uom = self.env.ref(
            "uom.product_uom_unit", raise_if_not_found=False
        )
        product_info_by_id = {
            prod.id: (
                prod.display_name or "",
                prod.tracking or "none",
                (
                    (prod.uom_id.name or "")
                    if uom_enabled and prod.uom_id != default_uom
                    else ""
                ),
            )
            for prod in active_moves.product_id
        }
        lines_by_move_id = {}
        for move, lines in all_lines.grouped("move_id").items():
            lines_by_move_id[move.id] = lines
        moves = []
        for mv in active_moves:
            move_lines = lines_by_move_id.get(mv.id, all_lines.browse())
            picked_all = bool(move_lines) and all(
                l.picked for l in move_lines
            )
            picked_lines = move_lines.filtered(
                lambda l: l.picked
            ).sorted(key=lambda l: l.id)
            picked_total = sum(l.quantity for l in picked_lines)
            # Group picked lines by (result_package_id, location_id) so each
            # package×location combination becomes its own product row.
            # This lets the card header show the source location per row and
            # keeps serial/lot grouping precise when the same product comes
            # from multiple locations into one package.
            package_groups = {}  # (pkg_id, pkg_name, loc_id, loc_name) -> [lines]
            # Default location for this move — used as fallback when the
            # move has no picked lines at all (nothing to derive a location
            # from), and when we synthesise the "unpacked remainder" row.
            default_loc_id = mv.location_id.id or False
            default_loc_name = (
                mv.location_id.display_name
                or location_name_by_id.get(default_loc_id, "")
            )
            default_dest_name = mv.location_dest_id.display_name or ""
            tracking = product_info_by_id.get(
                mv.product_id.id, ("", "none")
            )[1]
            grouped_lines = move_lines.filtered(
                lambda l: l.picked or l.package_id or l.result_package_id
            ).sorted(key=lambda l: l.id)
            for l in grouped_lines:
                pkg_id = (
                    l.result_package_id.id or l.package_id.id or False
                )
                pkg_name = package_name_by_id.get(pkg_id, "")
                # Serial-tracked moves stay on ONE card per package: each
                # serial row shows its own 从/至 inside the card body
                # (design rule 3). Other tracking modes split one card per
                # source location (design rule 2).
                if tracking == "serial":
                    loc_id, loc_name = default_loc_id, default_loc_name
                else:
                    loc_id = l.location_id.id or False
                    loc_name = location_name_by_id.get(loc_id, "")
                key = (pkg_id, pkg_name, loc_id, loc_name)
                if key not in package_groups:
                    package_groups[key] = []
                package_groups[key].append(l)
            if not package_groups:
                package_groups[(False, "", default_loc_id, default_loc_name)] = []
            # Whether the move has any packaged group (to decide showing
            # the "未装包" label on the unpacked group).
            has_packaged = any(k[0] for k in package_groups)
            # When part of the demand is already packaged, keep an unpacked
            # row for what is still outside any package (nothing picked yet),
            # so the operator sees the remainder as its own row instead of
            # losing it behind the package rows.
            has_unpacked = any(
                not (l.package_id or l.result_package_id) for l in move_lines
            )
            if (
                has_packaged
                and not any(not k[0] for k in package_groups)
                and picked_total < mv.product_uom_qty
                and has_unpacked
            ):
                package_groups[(False, "", default_loc_id, default_loc_name)] = []
            packed_picked = sum(
                l.quantity for l in picked_lines if l.result_package_id
            )
            for (pkg_id, pkg_name, loc_id, loc_name), lines in package_groups.items():
                # Show one entry per lot and picked state within this package
                # group. Multiple lines of the same lot contribute to one
                # picked quantity; other packages keep their own quantity.
                lots_by_key = {}
                for l in lines:
                    if not l.lot_id:
                        continue
                    lot_key = (l.lot_id.id, l.picked)
                    if lot_key not in lots_by_key:
                        lots_by_key[lot_key] = {
                            "id": l.lot_id.id,
                            "key": "%s_%s" % (
                                l.lot_id.id,
                                "picked" if l.picked else "reserved",
                            ),
                            "name": lot_name_by_id.get(l.lot_id.id, ""),
                            "picked": l.picked,
                            "picked_quantity": 0.0,
                            "reserved_quantity": 0.0,
                            # Per-lot 从/至: shown inside the serial row when
                            # one card mixes serials from different locations.
                            "location_name": location_name_by_id.get(
                                l.location_id.id, ""
                            ),
                            "location_dest_name": (
                                location_dest_name_by_id.get(
                                    l.location_dest_id.id, ""
                                )
                            ),
                            # Real move-line identities allow corrections to
                            # target one source/package line instead of the
                            # first line matching move + lot.
                            "lines": [],
                        }
                    if l.picked:
                        lots_by_key[lot_key]["picked_quantity"] += l.quantity
                    else:
                        lots_by_key[lot_key]["reserved_quantity"] += l.quantity
                    lots_by_key[lot_key]["lines"].append({
                        "id": l.id,
                        "quantity": l.quantity,
                        "location_id": l.location_id.id or False,
                        "location_name": location_name_by_id.get(
                            l.location_id.id, ""
                        ),
                        "package_id": pkg_id,
                        "package_name": pkg_name,
                    })
                # Reserved (unpicked) lots go to the unpacked group only.
                if show_reserved and not pkg_id:
                    reserved_lines = move_lines.filtered(
                        lambda l: not l.picked and l.lot_id
                        and not (l.package_id or l.result_package_id)
                    ).sorted(key=lambda l: l.id)
                    for l in reserved_lines:
                        lot_key = (l.lot_id.id, False)
                        if lot_key not in lots_by_key:
                            lots_by_key[lot_key] = {
                                "id": l.lot_id.id,
                                "key": "%s_reserved" % l.lot_id.id,
                                "name": lot_name_by_id.get(l.lot_id.id, ""),
                                "picked": False,
                                "picked_quantity": 0.0,
                                "reserved_quantity": 0.0,
                                "location_name": location_name_by_id.get(
                                    l.location_id.id, ""
                                ),
                                "location_dest_name": (
                                    location_dest_name_by_id.get(
                                        l.location_dest_id.id, ""
                                    )
                                ),
                                "lines": [],
                            }
                        lots_by_key[lot_key]["reserved_quantity"] += l.quantity
                lots = list(lots_by_key.values())
                picked_lot_ids = [
                    l.lot_id.id for l in lines if l.lot_id
                ]
                show_package_label = bool(pkg_name) or (not pkg_id and has_packaged)
                group_total = sum(l.quantity for l in lines)
                group_qty = sum(l.quantity for l in lines if l.picked)
                # Row-level demand: a package row shows the quantity it
                # holds, the unpacked row shows the demand not packaged yet.
                demand_qty = (
                    group_total if pkg_id
                    else max(mv.product_uom_qty - packed_picked, 0.0)
                )
                # Row-level 至：take the first line's destination, falling
                # back to the move's own destination for empty groups.
                row_dest_name = (
                    location_dest_name_by_id.get(
                        lines[0].location_dest_id.id, ""
                    )
                    if lines
                    else default_dest_name
                )
                # True when the serials inside this card come from / go to
                # more than one location — then each serial row shows its own
                # 从/至 and the card header hides the location line.
                row_picked = bool(lines) and all(l.picked for l in lines)
                lots_multi_location = len({
                    (lot.get("location_name", ""), lot.get("location_dest_name", ""))
                    for lot in lots
                }) > 1
                moves.append({
                    "id": mv.id,
                    "row_key": "%s_%s_%s" % (mv.id, pkg_id or "nopkg", loc_id or 0),
                    "product_name": product_info_by_id.get(
                        mv.product_id.id, ("", "none")
                    )[0],
                    "location_name": loc_name,
                    "location_dest_name": row_dest_name,
                    "lots_multi_location": lots_multi_location,
                    "product_uom_qty": mv.product_uom_qty,
                    "demand_qty": demand_qty,
                    "uom_name": product_info_by_id.get(
                        mv.product_id.id, ("", "none", "")
                    )[2],
                    "quantity": group_qty,
                    "picked": row_picked,
                    "tracking": product_info_by_id.get(
                        mv.product_id.id, ("", "none")
                    )[1],
                    "lots": lots,
                    "latest_lot_id": picked_lot_ids[-1] if picked_lot_ids else False,
                    "package_id": pkg_id,
                    "package_name": pkg_name,
                    "show_package_label": show_package_label,
                })

        # ---- Resolve origin document for the "source doc" button ----
        origin_info = self._resolve_picking_origin(picking)

        return {
            "wiz_id": self.id,
            "step": self.step,
            "scan_steps": scan_steps,
            "message": self.message or "",
            "message_type": self.message_type or "info",
            "picking_id": picking.id,
            "picking_name": picking.name or "",
            "picking_state": self.picking_state or "",
            "picking_type_code": self.picking_type_code or "",
            # Origin document (sale.order / purchase.order / ...).
            # Resolve from direct m2o links first, then fall back to the
            # plain `origin` char field (common in MRP/manual flows).
            "origin_model": origin_info["model"],
            "origin_id": origin_info["id"],
            "origin_name": origin_info["name"],
            # Picking form toolbar items — consumed by the native
            # ``web.CogMenu`` OWL component rendered in the top-right corner.
            "action_menu_items": self._get_picking_action_menu_items(),
            "barcode_lot_scan_policy": lot_scan_policy,
            "uom_enabled": uom_enabled,
            "location_id": self.location_id.id or False,
            "location_name": self.location_id.display_name or "",
            "location_dest_id": self.location_dest_id.id or False,
            "location_dest_name": (
                self.location_dest_id.display_name
                or self.picking_location_dest_id.display_name
                or ""
            ),
            "product_id": self.product_id.id or False,
            "product_name": self.product_id.display_name or "",
            "product_tracking": self.product_tracking or "none",
            "product_uom_name": self.product_uom_id.name or "",
            "lot_id": self.lot_id.id or False,
            "lot_name": self.lot_id.display_name or "",
            "product_qty": self.product_qty or 0.0,
            "qty_available": self.qty_available or 0.0,
            "total_demand": self.total_demand or 0.0,
            "total_done": self.total_done or 0.0,
            "visible_force_done": bool(self.visible_force_done),
            "visible_force_add": bool(self.visible_force_add),
            "scan_mode": self.scan_mode or "default",
            "mode_hint": self._get_mode_hint(),
            "package_scan_intent": self.package_scan_intent or "take",
            "cross_order_pending": bool(self.cross_order_pending),
            "visible_switch_selector": bool(self.visible_switch_selector),
            "pending_switch_pickings": [
                {"id": p.id, "name": p.name}
                for p in self.pending_switch_picking_ids
            ],
            "active_move_id": self.active_move_id.id or False,
            "active_move_product_name": (
                self.active_move_id.product_id.display_name or ""
                if self.active_move_id else ""
            ),
            # Package chooser of the unclaim-by-scan flow (quantity rows).
            "unclaim_product_id": self.unclaim_product_id.id or False,
            "unclaim_product_name": self.unclaim_product_id.display_name or "",
            "unclaim_choices": self.unclaim_choices or [],
            "rows": self._get_scan_rows_v4(),
            "move_ids": moves,
            # Packaging config
            "show_put_in_pack": self.env.user.has_group("stock.group_tracking_lot"),
            # Global "Packages" setting: when off, the scan view drops the
            # whole package layer (stack frame + package bar) and shows the
            # product cards directly on the page background.
            "packages_enabled": self.env.user.has_group("stock.group_tracking_lot"),
            "pack_required": picking.picking_type_id.barcode_require_pack == "mandatory",
            "lines_need_pack": self._lines_need_pack(picking),
        }

    @api.model
    def _resolve_picking_origin(self, picking):
        """Best-effort resolution of the picking's origin document.

        Priority: direct Many2one links (sale_id, purchase_id, ...) on the
        picking itself, then the plain ``origin`` char field which stores
        the source document's ``_name`` (e.g. MRP, manual).

        Returns a dict with model / id / name, all False if no origin
        can be identified — the frontend then disables/hides the button.
        """
        if not picking:
            return {"model": False, "id": False, "name": ""}

        # 1) Known direct m2o links on stock.picking
        for fname in ("sale_id", "purchase_id"):
            if fname in picking._fields:
                rel = picking[fname]
                if rel:
                    return {
                        "model": rel._name,
                        "id": rel.id,
                        "name": rel.display_name or "",
                    }

        # 2) origin char field — try to match by name in common origin models
        origin_name = (picking.origin or "").strip()
        if origin_name:
            # sale.order
            so = self.env["sale.order"].search(
                [("name", "=", origin_name)], limit=1
            )
            if so:
                return {"model": "sale.order", "id": so.id, "name": so.name}
            # purchase.order
            po = self.env["purchase.order"].search(
                [("name", "=", origin_name)], limit=1
            )
            if po:
                return {"model": "purchase.order", "id": po.id, "name": po.name}
            # mrp.production
            mp = self.env["mrp.production"].search(
                [("name", "=", origin_name)], limit=1
            )
            if mp:
                return {"model": "mrp.production", "id": mp.id, "name": mp.name}

        return {"model": False, "id": False, "name": ""}

    def _lines_need_pack(self, picking):
        """Whether validation requires all picked lines to be packed."""
        pt = picking.picking_type_id
        require = pt.barcode_require_pack
        if require == "mandatory":
            return True
        if require == "optional" and pt.barcode_validation_all_packed:
            return True
        return False

    # --- Step index helper (方案 C 扩展点) ---
    def _step_index(self, key):
        """Return the list index of step ``key`` in ``_get_scan_steps()``.

        Uses assert so a typo'd key fails loud in development instead of
        silently falling back to step 0 (which would mask routing bugs).
        Normal call paths always pass a key present in the current
        picking type's step list.
        """
        self.ensure_one()
        steps = self._get_scan_steps()
        assert key in steps, (
            "step key %r not in %r — check _get_scan_steps()" % (key, steps)
        )
        return steps.index(key)

    # --- Barcode entry points ---
    def on_barcode_scanned(self, barcode):
        """Hardware path: core barcode_handler widget writes
        ``_barcode_scanned`` → core mixin onchange calls this. Processes
        directly and deliberately does NOT write ``barcode``, so the
        client-side onchange chain can never double-fire the manual
        entry handler below.
        """
        self._process_barcode(barcode.strip() if barcode else "")

    @api.onchange("barcode")
    def _onchange_barcode_scan(self):
        """Manual scan box path: the visible ``barcode`` char field is
        the scan entry for tablets/browsers without a hardware scanner.
        Clears the value so the same code can be scanned twice in a row.
        """
        if self.barcode:
            barcode = self.barcode
            self.barcode = False
            self._barcode_scanned = False
            self._process_barcode(barcode)
        # onchange methods must return None or a dict.

    # --- Dispatch chain ---
    def _process_barcode(self, barcode):
        """Main barcode dispatch: picking → location → product → lot.

        Each scanner returns True when it claims the barcode, False to
        let the next scanner try (penetration rule). The only exception
        is a barcode that is clearly a picking name but the picking is
        not in a scannable state — that returns True with an error.
        """
        if not barcode:
            return
        # A new scan supersedes any pending over-demand confirmation.
        self.pending_add = False
        self.visible_force_done = False
        # While the candidate-picking selector is open, only picking-name
        # scans are allowed. Blocking product/lot scans here prevents an
        # ambiguous picking scan from silently writing into the current
        # (possibly wrong) picking.
        if self.visible_switch_selector:
            if not self._scan_picking(barcode):
                self._set_message(
                    "error",
                    self.env._("Select a transfer or scan a transfer name to continue"),
                )
            return True
        if self.visible_force_add:
            self._set_message(
                "more_match",
                self.env._(
                    "Confirm or cancel adding the current product before "
                    "scanning another barcode."
                ),
            )
            return True
        mode = self.scan_mode or "default"
        if mode in ("split_scan", "unclaim_scan"):
            if self._scan_in_mode(barcode, mode):
                return True
            self._set_message(
                "error",
                self.env._(
                    "Scan a product, lot/serial number or package in this mode."
                ),
            )
            return True
        if self._scan_picking(barcode):
            return True
        if self._scan_location(barcode):
            return True
        if self._scan_dest_location(barcode):
            return True
        if self._scan_product(barcode):
            return True
        if self._scan_lot(barcode):
            return True
        if self._scan_package(barcode):
            return True
        self._set_message("not_found", self.env._("Barcode not found: %s", barcode))
        return True

    def _check_selector_resolved(self):
        """Server-side guard: reject write actions while the candidate-
        picking selector is open.

        When ``_scan_picking`` hits a multi-match, ``picking_id`` still
        points at the OLD picking and the selector is open. The
        ``_process_barcode`` guard blocks barcode scans, but action RPCs
        (consume, validate, force-add) would still write to the old
        picking. This shared guard enforces resolution at the entry of
        every action that mutates picking data. Returns True if clear,
        False (with error message) if the selector is still open.
        """
        self.ensure_one()
        if self.visible_switch_selector:
            self._set_message(
                "error",
                self.env._("Select a transfer first before continuing"),
            )
            return False
        return True

    def process_barcode_and_dispatch(self, barcode):
        """One-shot RPC entry for the OWL PickingScanApp client action.

        Runs ``_process_barcode`` then returns ``{action, state}`` where
        ``action`` is None or an act_window dict (e.g. backorder wizard
        from action_validate_picking, or candidate-picking selector).
        ``state`` is the JSON-serializable wizard snapshot.
        """
        self.ensure_one()
        self._process_barcode(barcode)
        return {
            "action": None,
            "state": self.get_scan_state(),
        }

    # --- Scanners ---
    def _scan_picking(self, barcode):
        """Scan-first picking switching by picking reference (name).

        Matches picking.name exactly. Inactive pickings (draft/done/
        cancel) error out without falling through. Single active match
        switches directly; multi-match is out of scope for outgoing
        (no ambiguous selector yet).
        """
        self.ensure_one()
        active_states = ("confirmed", "assigned", "partially_available")
        # One search instead of search + search_count: an inactive picking
        # (draft/done/cancel) must still raise the explicit state error
        # rather than fall through to the product scanner, so the whole
        # name match is fetched and partitioned here.
        pickings = self.env["stock.picking"].search([("name", "=", barcode)])
        active_pickings = pickings.filtered(
            lambda p: p.state in active_states
        )
        if not active_pickings:
            if pickings:
                self._set_message(
                    "error",
                    self.env._("Transfer %s is not active (draft/done/cancelled)", barcode),
                )
                return True
            return False
        pickings = active_pickings
        if len(pickings) > 1:
            # Multiple active pickings share this name. Populate the
            # candidate selector and open it. The dispatch guard below
            # blocks product/lot scans until the user picks one, so an
            # ambiguous scan can never write to the wrong picking.
            self.pending_switch_picking_ids = [(6, 0, pickings.ids)]
            self.visible_switch_selector = True
            self._set_message(
                "more_match",
                self.env._("Multiple transfers found for barcode: %s. Select one.", barcode),
            )
            return True
        picking = pickings
        if self.picking_id == picking:
            self._set_message("info", self.env._("Already on transfer %s", picking.name))
            return True
        self._switch_picking(picking)
        return True

    def _scan_location(self, barcode):
        # Source-location scanning is opt-in per operation type. When it
        # is off the operator never scans a location, so skip the lookup
        # entirely: every barcode used to pay one stock.location SELECT.
        if not self.barcode_scan_source_location:
            return False
        # Only internal (physical stock) locations are valid source
        # locations for picking. Customer/supplier/virtual locations are
        # rejected with a distinct message so the operator knows whether
        # the barcode is wrong or the location type is wrong.
        any_location = self.env["stock.location"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not any_location:
            return False
        if any_location.usage != "internal":
            self._set_message(
                "error",
                self.env._("%s is not a stock location (only internal locations "
                  "can be scanned)", any_location.name),
            )
            return True
        location = any_location
        self.location_id = location
        # Advance to the next step (dest_location if required, else
        # product). Using step+1 instead of a hardcoded step key keeps
        # the flow correct regardless of the picking type config.
        self.step += 1
        self._set_message_step()
        return True

    def _scan_dest_location(self, barcode):
        """Scan the destination location.

        Only triggered when the picking type has
        ``barcode_scan_dest_location`` enabled. Internal locations are
        accepted (the destination of an internal transfer is a stock
        location); customer/supplier locations are also accepted for
        outgoing/incoming pickings.
        """
        # Destination scanning is opt-in as well; skip the lookup for the
        # operation types that do not scan it (saves one SELECT per scan).
        if not self.barcode_scan_dest_location:
            return False
        any_location = self.env["stock.location"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not any_location:
            return False
        # For destination, accept internal, customer, and supplier
        # locations (outgoing → customer, incoming → supplier,
        # internal → internal). Reject only virtual/inventory/scrap.
        if any_location.usage in ("view", "inventory", "production"):
            self._set_message(
                "error",
                self.env._("%s is not a valid destination location", any_location.name),
            )
            return True
        self.location_dest_id = any_location
        self.step = self._step_index("product")
        self._set_message_step()
        return True

    def _get_lot_scan_policy(self):
        self.ensure_one()
        return (
            self.picking_id.picking_type_id.barcode_lot_scan_policy
            or "mandatory"
        )

    def _get_reserved_lot_candidates(self, moves, lot=None):
        """Return (unpicked line, lot) pairs in reservation order."""
        product = moves[:1].product_id
        lines = moves.move_line_ids.filtered(
            lambda line: (
                not line.picked
                and not line.result_package_id
                and (line.lot_id or line.lot_name)
                and line.quantity > 0
                and (not self.location_id or line.location_id == self.location_id)
            )
        ).sorted(key=lambda line: line.id)
        lot_by_name = {reserved_lot.name: reserved_lot for reserved_lot in lines.lot_id}
        missing_names = {
            line.lot_name for line in lines
            if not line.lot_id and line.lot_name and line.lot_name not in lot_by_name
        }
        if missing_names:
            found_lots = self.env["stock.lot"].search([
                ("product_id", "=", product.id),
                ("name", "in", list(missing_names)),
            ])
            lot_by_name.update({reserved_lot.name: reserved_lot for reserved_lot in found_lots})
        all_lines = moves.move_line_ids
        candidates = []
        for line in lines:
            reserved_lot = line.lot_id or lot_by_name.get(line.lot_name)
            if not reserved_lot or (lot and reserved_lot != lot):
                continue
            if product.tracking == "serial" and all_lines.filtered(
                lambda picked_line: picked_line.picked and picked_line.lot_id == reserved_lot
            ):
                continue
            candidates.append((line, reserved_lot))
        return candidates

    def _pick_reserved_lots(self, moves, quantity, lot=None):
        """Move quantity from reserved lines to picked lines without losing lots."""
        self.ensure_one()
        product = moves[:1].product_id
        if not product or product.tracking == "none" or quantity <= 0:
            return {}
        rounding = product.uom_id.rounding
        if product.tracking == "serial" and float_compare(
            quantity, 1.0, precision_rounding=rounding
        ):
            return {}
        all_lines = moves.move_line_ids
        total_demand = sum(moves.mapped("product_uom_qty"))
        picked_qty = sum(line.quantity for line in all_lines if line.picked)
        if (
            float_compare(
                picked_qty + quantity, total_demand,
                precision_rounding=rounding,
            ) > 0
            and self._get_excess_qty_policy() != "allow"
        ):
            return {}
        candidates = self._get_reserved_lot_candidates(moves, lot=lot)
        if product.tracking == "serial":
            available = sum(
                1.0 for line, _lot in candidates
                if float_compare(line.quantity, 1.0, precision_rounding=rounding) >= 0
            )
        else:
            available = sum(line.quantity for line, _lot in candidates)
        if float_compare(available, quantity, precision_rounding=rounding) < 0:
            return {}

        remaining = quantity
        move_lines_dic = {}
        for line, reserved_lot in candidates:
            if float_is_zero(remaining, precision_rounding=rounding):
                break
            if product.tracking == "serial":
                if float_compare(line.quantity, 1.0, precision_rounding=rounding) < 0:
                    continue
                take = 1.0
            else:
                take = min(line.quantity, remaining)
            if not line.lot_id:
                line.lot_id = reserved_lot.id
                line.lot_name = reserved_lot.name
            picked_line = self.env["stock.move.line"]
            if product.tracking != "serial":
                picked_line = line.move_id.move_line_ids.filtered(
                    lambda candidate: (
                        candidate.picked
                        and not candidate.result_package_id
                        and candidate.lot_id == reserved_lot
                        and candidate.location_id == line.location_id
                        and candidate.location_dest_id == line.location_dest_id
                    )
                )[:1]
            if picked_line:
                picked_line.quantity += take
                line.quantity -= take
                if float_is_zero(line.quantity, precision_rounding=rounding):
                    line.unlink()
            elif not float_compare(
                take, line.quantity, precision_rounding=rounding
            ):
                line.picked = True
                picked_line = line
            else:
                line.quantity -= take
                picked_line = line.copy({"quantity": take, "picked": True})
            move_lines_dic[picked_line.move_id.id] = picked_line
            remaining -= take
        return move_lines_dic

    def action_pick_reserved_lot(self, move_id, lot_id, quantity=1.0):
        """Pick an exact reserved lot/SN from the OWL line buttons."""
        self.ensure_one()
        if self._get_lot_scan_policy() != "optional":
            self._set_message(
                "error",
                self.env._("Lot/Serial scanning is mandatory for this operation type."),
            )
            return False
        move = self.picking_id.move_ids.filtered(
            lambda candidate: candidate.id == move_id and candidate.state != "cancel"
        )
        lot = self.env["stock.lot"].browse(lot_id)
        if not move or not lot.exists() or lot.product_id != move.product_id:
            return False
        try:
            quantity = float(quantity)
        except (TypeError, ValueError):
            return False
        if quantity <= 0:
            return False
        result = self._pick_reserved_lots(move, quantity, lot=lot)
        if not result:
            self._set_message(
                "error",
                self.env._(
                    "Insufficient reserved quantity for %(lot)s, or the quantity "
                    "would exceed demand. Scan the lot/serial instead.",
                    lot=lot.name,
                ),
            )
            return False
        product_name = move.product_id.name
        self._clean_values()
        self._set_message(
            "success",
            self.env._(
                "Picked reserved lot/serial: %(prod)s x%(qty)s",
                prod=product_name,
                qty=quantity,
            ),
        )
        return result

    def _scan_product(self, barcode):
        # type='consu' = Goods (physical products, excludes service/combo).
        # NOTE: do NOT add is_storable=True here. Adding it would EXCLUDE
        # consumables (type='consu' with is_storable=False) that can
        # legitimately appear on a picking — stock.move._should_bypass_
        # reservation skips reservation for them but they still flow
        # through picking. The real admittance gate is the
        # picking.move_ids membership check below.
        domain = [("barcode", "=", barcode), ("type", "=", "consu")]
        products = self.env["product.product"].search(domain)
        if not products:
            return False
        if len(products) > 1:
            self._set_message("more_match", self.env._("Multiple products found"))
            return True
        product = products
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return True
        # Check the product belongs to this picking's moves
        component_moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if not component_moves:
            return self._scan_outside_product(product)
        self.product_id = product
        # Keep the row highlight in sync with the scanned product so the
        # operator can keep scanning the same product without re-clicking.
        self.active_move_id = (
            component_moves[:1]
            if not self.active_move_id
            or self.active_move_id.product_id != product
            else self.active_move_id
        )
        self.product_uom_id = product.uom_id
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 1.0
        self._compute_qty_available()
        if product.tracking != "none":
            if self._get_lot_scan_policy() == "optional":
                result = self._pick_reserved_lots(component_moves, 1.0)
                if result:
                    self._clean_values()
                    self._set_message(
                        "success",
                        self.env._(
                            "Picked reserved lot/serial: %(prod)s x1",
                            prod=product.name,
                        ),
                    )
                    return True
            self._set_message(
                "info", self.env._("Product: %s. Scan lot.", product.name)
            )
            self.step = self._step_index("lot")
        else:
            # Quantity-tracked product: one product scan picks one unit,
            # exactly like the row's +1 button. The unit lands on the
            # unpacked remainder of the active move (the pack flow binds
            # it to a package afterwards) and the picking type's
            # over-pick policy still decides whether it may be added.
            move = self.active_move_id
            target_qty = sum(
                self._untracked_scope_lines(move, False).mapped("quantity")
            ) + 1.0
            self._set_untracked_move_qty(move, target_qty, False)
            # Keep the product selected so the "Consume by demand"
            # shortcut stays available, but clear the quantity: leaving
            # 1.0 here would show a confirm button that SETs the line
            # back to a single unit.
            self.product_id = product
            self.lot_id = False
            self.lot_name = False
            self.product_qty = 0.0
            self.qty_available = 0.0
            self.step = self._step_index("product")
            # visible_force_done is intentionally left as set by the
            # over-pick policy: a 'warn' block must keep its force button.
            return True
        self._set_message_step()
        return True

    def _scan_outside_product(self, product):
        """Handle a scanned product that is not part of the transfer.

        Quantity-tracked products follow the picking type's
        ``barcode_new_product_policy``:
          - ``allow``: add one unit immediately (new move, picked);
          - ``warn``: preview it and wait for the footer confirmation;
          - ``forbid``: keep the explicit "not part of this transfer" error.
        Tracked products still require a lot/serial scan to know what is
        being received; they are allowed only for empty pickings created
        from the workbench (``allow_new_products``).
        """
        self.ensure_one()
        if product.tracking != "none":
            if not self.allow_new_products:
                self._set_message(
                    "error",
                    self.env._(
                        "Product %(name)s is not part of this transfer",
                        name=product.name,
                    ),
                )
                return True
            # Empty picking created from the workbench: the lot/serial
            # identifies the product, and _scan_new_product_lot creates the
            # move once the lot is scanned.
            self.product_id = product
            self.product_uom_id = product.uom_id
            self.lot_id = False
            self.lot_name = False
            self.product_qty = 1.0
            self.active_move_id = False
            self._set_message(
                "info", self.env._("Product: %s. Scan lot.", product.name)
            )
            self.step = self._step_index("lot")
            return True
        if self._get_new_product_policy() == "forbid":
            self._set_message(
                "error",
                self.env._(
                    "Product %(name)s is not part of this transfer",
                    name=product.name,
                ),
            )
            return True
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 1.0
        self.active_move_id = False
        if self._get_new_product_policy() == "warn":
            self.visible_force_add = True
            self._set_message(
                "more_match",
                self.env._(
                    "Product %(product)s is not in transfer %(picking)s. "
                    "Confirm adding 1 unit and picking it.",
                    product=product.name,
                    picking=self.picking_id.name,
                ),
            )
            return True
        self.action_force_add(product_id=product.id)
        return True

    def _scan_lot(self, barcode):
        search_product = self.product_id
        if not search_product and self.active_move_id:
            search_product = self.active_move_id.product_id
        if not search_product:
            # Nothing selected yet: resolve the product from the serial so
            # the operator can scan serial numbers straight away instead
            # of scanning the product barcode or tapping a row first.
            return self._scan_lot_fallback(barcode)
        if search_product.tracking == "none":
            # A globally unique existing serial still identifies its product
            # when a non-tracked product happens to be selected.
            return self._scan_lot_fallback(barcode)
        lot_domain = [("name", "=", barcode), ("product_id", "=", search_product.id)]
        lots = self.env["stock.lot"].search(lot_domain)
        if not lots:
            return self._scan_lot_fallback(barcode)
        if len(lots) > 1:
            self._set_message("more_match", self.env._("Multiple lots found"))
            return True
        lot = lots
        if self.allow_new_products and not self.picking_id.move_ids.filtered(
            lambda m: m.product_id == lot.product_id and m.state != "cancel"
        ):
            # Empty transfer from the workbench: there is no move to write on,
            # so create it from the scanned lot instead of using the generic
            # confirm path.
            result = self._scan_new_product_lot(lot, lot.product_id)
            if self.allow_new_products:
                # Confirmation may have reserved the same serial again on
                # another source sub-location; keep only the picked line.
                duplicates = self.env["stock.move.line"].search(
                    [
                        ("picking_id", "=", self.picking_id.id),
                        ("product_id", "=", lot.product_id.id),
                        ("lot_id", "=", lot.id),
                        ("picked", "=", False),
                    ]
                )
                duplicates.unlink()
            return result
        self.lot_id = lot
        self.lot_name = lot.name
        self.product_id = lot.product_id
        self.product_uom_id = lot.product_id.uom_id
        lot_quants = self._compute_qty_available()
        if self.product_tracking == "serial":
            self.product_qty = 1.0
            # No location fallback: serial auto-confirm will fail in
            # action_confirm ("No source location scanned") until the
            # operator scans the source location.
            self.action_confirm(lot_quants=lot_quants)
            return True
        self._confirm_scanned_lot(lot_quants=lot_quants)
        return True

    def _scan_lot_fallback(self, barcode):
        """The scanned barcode is not a lot of the current product.

        Two-tier lookup before treating it as a new lot:
          1. Global lot name search (company-scoped).
          2. Product barcode search (company-scoped).
        """
        self.ensure_one()
        if not self.picking_id or not self.company_id:
            return self._create_new_lot_flow(barcode)
        lots = self.env["stock.lot"].search([
            ("name", "=", barcode),
            ("company_id", "in", [self.company_id.id, False]),
        ])
        if len(lots) > 1:
            narrowed = lots
            if self.active_move_id:
                narrowed = narrowed.filtered(
                    lambda l: l.product_id == self.active_move_id.product_id
                )
            elif self.product_id:
                narrowed = narrowed.filtered(
                    lambda l: l.product_id == self.product_id
                )
            if len(narrowed) > 1 and self.picking_id:
                picking_products = self.picking_id.move_ids.mapped("product_id")
                narrowed = narrowed.filtered(
                    lambda l: l.product_id in picking_products
                )
            if len(narrowed) == 1:
                return self._resolve_lot_owner(narrowed, narrowed.product_id)
            self._set_message(
                "more_match",
                self.env._("Multiple lots named %(sn)s found. Click the target "
                  "product row first, then scan again.", **{"sn": barcode}),
            )
            return True
        if len(lots) == 1:
            return self._resolve_lot_owner(lots, lots.product_id)
        products = self.env["product.product"].search([
            ("barcode", "=", barcode),
            ("company_id", "in", [self.company_id.id, False]),
        ])
        if len(products) > 1:
            self._set_message(
                "more_match",
                self.env._("Multiple products found for barcode: %s", barcode),
            )
            return True
        if len(products) == 1:
            return self._resolve_lot_owner(self.env["stock.lot"], products)
        return self._create_new_lot_flow(barcode)

    def _create_new_lot_flow(self, barcode):
        """Treat an unknown barcode as a new lot for the current product.

        When the picking's operation type does not allow creating new
        lots/serial numbers (``use_create_lots`` is False), unknown
        barcodes are rejected immediately with a clear error instead of
        silently creating a lot that would only fail at validation time.
        """
        self.ensure_one()
        # A package name must never be swallowed as a new lot: the package
        # scanner runs after this one, so let the barcode fall through.
        if self._is_package_barcode(barcode):
            return False
        if not self.product_id and self.active_move_id:
            self.product_id = self.active_move_id.product_id
            self.product_uom_id = self.product_id.uom_id
        # If the current product is already fully picked (or over), the
        # unknown barcode almost certainly belongs to a *different*
        # product. Don't create a new lot under the stale product — that
        # would trigger a spurious "quantity exceeds demand" against the
        # full product's demand. Clear the stale context and ask the
        # operator to scan the product barcode first.
        if self.product_id:
            move = self.picking_id.move_ids.filtered(
                lambda m: m.product_id == self.product_id and m.state != "cancel"
            )[:1]
            if move:
                picked = sum(
                    l.quantity for l in move.move_line_ids if l.picked
                )
                # The explicit "allow" policy overrides this heuristic:
                # the operator may intentionally receive extra serials,
                # and action_confirm will record the over-picked quantity.
                if (
                    picked >= move.product_uom_qty
                    and self._get_excess_qty_policy() != "allow"
                ):
                    self.product_id = False
                    self.lot_id = False
                    self.lot_name = False
                    self.active_move_id = False
                    self._set_message(
                        "info",
                        self.env._("Product %(name)s is fully picked. Scan the "
                          "next product barcode, then scan its lot.", **{"name": move.product_id.name}),
                    )
                    return True
        # Check the operation type before requiring a product: when the
        # operator scans serial numbers first, an unknown code means the
        # serial does not exist, so that must be the message even if no
        # product context is set yet.
        if not self.picking_id.use_create_lots:
            self._set_message(
                "error",
                self.env._("Serial number/lot %(name)s does not exist. This "
                  "operation type does not allow creating new ones.", **{"name": barcode}),
            )
            return True
        if not self.product_id:
            self._set_message(
                "error",
                self.env._("Scan a product barcode or click a product row first."),
            )
            return True
        self.lot_name = barcode
        self.lot_id = False
        self.qty_available = 0.0
        if self.product_id.tracking == "serial":
            self.product_qty = 1.0
            # No location fallback: serial auto-confirm will fail in
            # action_confirm ("No source location scanned") until the
            # operator scans the source location.
            self.action_confirm()
            return True
        self._confirm_scanned_lot()
        return True

    def _find_package_by_barcode(self, barcode):
        """Return the stock.package whose name equals ``barcode``, if any."""
        if not barcode:
            return self.env["stock.package"]
        return self.env["stock.package"].search(
            [("name", "=", barcode)], limit=1
        )

    def _is_package_barcode(self, barcode):
        """True when ``barcode`` is an existing package name.

        Used by the lot scanner so a package name is never swallowed as a
        new lot; the package scanner runs after it and must see the code.
        """
        return bool(self._find_package_by_barcode(barcode))

    def _scan_package(self, barcode):
        """Scan a package barcode: whole-package pick, or pack if intended.

        The meaning is explicit, never guessed: by default a scanned
        package is picked as a whole; after the operator pressed "Pack"
        the very same scan binds the unpacked picked lines to it. Returns
        False (let other scanners try) when no package matches.
        """
        self.ensure_one()
        if not self.picking_id:
            return False
        package = self._find_package_by_barcode(barcode)
        if not package:
            return False
        if (self.scan_mode or "default") == "pack":
            handled = self._bind_to_package(package)
            if handled:
                # Deliveries treat "pack" as a one-shot command; receipts
                # keep packing package after package, so both fall back to
                # the direction default instead of a hard-coded value.
                self.scan_mode = self._default_scan_mode()
            return handled
        return self._process_package_scan(package)

    def _process_package_scan(self, package):
        """Pick every unpicked line of this transfer that sits in ``package``.

        Whole-package pick: quantity and package assignment stay as they
        are, only ``picked`` flips to True. Over-picking follows the
        operation type policy and never writes when the policy forbids it.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        lines = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("picked", "=", False),
            "|",
            ("package_id", "=", package.id),
            ("result_package_id", "=", package.id),
        ])
        if not lines:
            return self._report_package_scan_empty(package)
        # A line whose source package contradicts the scanned one is data
        # corruption: skip it instead of silently repointing the package.
        inconsistent = lines.filtered(
            lambda line: line.package_id and line.package_id != package
        )
        lines -= inconsistent
        if not lines:
            return self._report_package_scan_empty(package)
        if self._package_scan_exceeds_demand(lines):
            policy = self._get_excess_qty_policy()
            forced = bool(self.env.context.get("force_package_scan"))
            if policy == "forbid" or (policy == "warn" and not forced):
                self._set_message(
                    "error" if policy == "forbid" else "more_match",
                    self.env._(
                        "Package %(pkg)s exceeds the remaining demand of "
                        "this transfer.",
                        pkg=package.name,
                    ),
                )
                return True
        lines.write({"picked": True, "result_package_id": package.id})
        # Only fill the source package when the line has none: a different
        # value means the goods were not physically in the scanned package.
        lines.filtered(lambda line: not line.package_id).write({
            "package_id": package.id,
        })
        self._set_message(
            "success",
            self.env._(
                "Package %(pkg)s: %(count)s line(s) picked.",
                pkg=package.name,
                count=len(lines),
            ),
        )
        return True

    def _package_scan_exceeds_demand(self, lines):
        """True when ``lines`` would push any move past its demand."""
        self.ensure_one()
        for move in lines.move_id:
            if move.product_uom_qty <= 0:
                # No demand to compare against (package-only transfer).
                continue
            move_lines = lines.filtered(lambda line: line.move_id == move)
            picked_elsewhere = sum(
                move.move_line_ids.filtered(lambda l: l.picked).mapped("quantity")
            )
            remaining = move.product_uom_qty - picked_elsewhere
            package_qty = sum(move_lines.mapped("quantity"))
            if float_compare(
                package_qty,
                remaining,
                precision_rounding=move.product_id.uom_id.rounding,
            ) > 0:
                return True
        return False

    def _report_package_scan_empty(self, package):
        """Explain why a package scan produced nothing, then stop."""
        other_lines = self.env["stock.move.line"].search_count([
            ("state", "not in", ("done", "cancel")),
            "|",
            ("package_id", "=", package.id),
            ("result_package_id", "=", package.id),
        ])
        if not package.quant_ids and not other_lines:
            self._set_message(
                "error",
                self.env._("Package %(pkg)s is empty.", pkg=package.name),
            )
        else:
            self._set_message(
                "error",
                self.env._(
                    "Package %(pkg)s holds no product for this transfer. "
                    "Press 'Pack' to put products into it.",
                    pkg=package.name,
                ),
            )
        return True

    def get_picking_packages(self):
        """Packages used by this transfer, for the split dialog."""
        self.ensure_one()
        if not self.picking_id:
            return []
        lines = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("result_package_id", "!=", False),
        ])
        packages = {}
        for line in lines:
            package = line.result_package_id
            entry = packages.setdefault(package.id, {
                "id": package.id,
                "name": package.name,
                "line_count": 0,
                "quantity": 0.0,
            })
            entry["line_count"] += 1
            entry["quantity"] += line.quantity
        return sorted(packages.values(), key=lambda item: item["name"])

    def action_set_pack_intent(self):
        """Toggle the one-shot 'pack into package' intent."""
        self.ensure_one()
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return False
        if (self.scan_mode or "default") == "pack":
            self.scan_mode = "default"
            self._set_message(
                "info",
                self.env._(
                    "Pack cancelled: scanning a package picks it as a whole."
                ),
            )
        else:
            self.scan_mode = "pack"
            self._set_message(
                "info",
                self.env._("Pack intent: scan or select the target package."),
            )
        return True

    def _get_mode_hint(self):
        """Operator-facing description of the current scan mode."""
        self.ensure_one()
        return {
            "default": self.env._(
                "Scan a package to pick the whole package."
            ),
            "pack": self.env._(
                "Packing: scan or select the target package."
            ),
            "split_scan": self.env._(
                "Removing package: scan a product, lot/serial or package."
            ),
            "unclaim_scan": self.env._(
                "Unclaiming: scan a product, lot/serial or package. "
                "Reservations are kept."
            ),
        }.get(self.scan_mode or "default", "")

    def action_set_scan_mode(self, mode):
        """Switch the scan semantics (default/pack/split_scan/unclaim_scan)."""
        self.ensure_one()
        valid = [key for key, _label in self._fields["scan_mode"].selection]
        if mode not in valid:
            self._set_message("error", self.env._("Unknown scan mode."))
            return False
        self.scan_mode = mode
        self.unclaim_product_id = False
        self.unclaim_choices = []
        self.pending_add = False
        self.visible_force_done = False
        return True

    def action_exit_scan_mode(self):
        """Back to the normal picking mode, per transfer direction."""
        self.ensure_one()
        self.scan_mode = self._default_scan_mode()
        self.unclaim_product_id = False
        self.unclaim_choices = []
        self.pending_add = False
        self.visible_force_done = False
        return True

    def action_remove_package(self, package_id):
        """Split dialog: drop one package from every line of this transfer."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        package = self.env["stock.package"].browse(package_id)
        if not package.exists():
            self._set_message("error", self.env._("Package not found."))
            return False
        lines = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("result_package_id", "=", package.id),
        ])
        if not lines:
            self._set_message(
                "info",
                self.env._(
                    "Package %(pkg)s is not used by this transfer.",
                    pkg=package.name,
                ),
            )
            return True
        lines.write({"result_package_id": False})
        self._set_message(
            "success",
            self.env._(
                "Package %(pkg)s removed from %(count)s line(s).",
                pkg=package.name,
                count=len(lines),
            ),
        )
        return True

    def _scan_in_mode(self, barcode, mode):
        """Apply split_scan / unclaim_scan to whatever the barcode matches."""
        self.ensure_one()
        package = self._find_package_by_barcode(barcode)
        if package:
            lines = self.env["stock.move.line"].search([
                ("picking_id", "=", self.picking_id.id),
                ("state", "not in", ("done", "cancel")),
                "|",
                ("package_id", "=", package.id),
                ("result_package_id", "=", package.id),
            ])
            return self._apply_mode_to_lines(lines, mode, package.name)
        product = self.env["product.product"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if product:
            if product.tracking == "none" and mode == "unclaim_scan":
                # One scan unclaims one unit; when those units live in
                # several packages the operator picks the package first.
                return self._unclaim_scanned_product(product)
            if product.tracking == "none" and mode == "split_scan":
                # One scan moves one unit out of its package (loose);
                # a product spread over several packages asks which one.
                return self._split_scanned_product(product)
            lines = self.env["stock.move.line"].search([
                ("picking_id", "=", self.picking_id.id),
                ("state", "not in", ("done", "cancel")),
                ("product_id", "=", product.id),
            ])
            return self._apply_mode_to_lines(lines, mode, product.display_name)
        lot = self.env["stock.lot"].search(
            [("name", "=", barcode)], limit=1
        )
        if lot:
            if mode == "unclaim_scan" and lot.product_id.tracking == "lot":
                # Scanning a batch cancels one unit (serial stays 1/line).
                return self._unclaim_scanned_lot(lot)
            lines = self.env["stock.move.line"].search([
                ("picking_id", "=", self.picking_id.id),
                ("state", "not in", ("done", "cancel")),
                ("lot_id", "=", lot.id),
            ])
            return self._apply_mode_to_lines(lines, mode, lot.name)
        return False

    def _apply_mode_to_lines(self, lines, mode, label):
        """Write the mode change on the matching lines and report it."""
        self.ensure_one()
        if mode == "split_scan":
            lines = lines.filtered("result_package_id")
            if not lines:
                self._set_message(
                    "info",
                    self.env._(
                        "%(label)s has no package to remove.", label=label
                    ),
                )
                return True
            lines.write({"result_package_id": False})
            self._set_message(
                "success",
                self.env._(
                    "Package removed from %(count)s line(s) of %(label)s.",
                    count=len(lines),
                    label=label,
                ),
            )
            return True
        lines = lines.filtered("picked")
        if not lines:
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no picked line to unclaim.", label=label
                ),
            )
            return True
        lines.write({"picked": False})
        self._set_message(
            "success",
            self.env._(
                "Unclaimed %(count)s line(s) of %(label)s. Reservations kept.",
                count=len(lines),
                label=label,
            ),
        )
        return True

    def _get_unclaim_groups(self, product, require_package=False):
        """Picked units of ``product`` grouped by destination package.

        Returns one dict per package (ordered by the first picked line),
        plus one for the unpacked remainder keyed by ``package_id``
        False. Each dict is ``{package_id, package_name, quantity}``.
        ``require_package`` skips the unpacked remainder, which is what
        the split (remove from package) flow needs.
        """
        self.ensure_one()
        lines = self.picking_id.move_ids.filtered(
            lambda move: (
                move.product_id == product
                and move.state not in ("done", "cancel")
            )
        ).move_line_ids.filtered("picked").sorted(lambda line: line.id)
        if require_package:
            lines = lines.filtered("result_package_id")
        groups = {}
        for line in lines:
            pkg_id = line.result_package_id.id or False
            group = groups.get(pkg_id)
            if not group:
                group = {
                    "package_id": pkg_id,
                    "package_name": line.result_package_id.name or "",
                    "quantity": 0.0,
                }
                groups[pkg_id] = group
            group["quantity"] += line.quantity
        return list(groups.values())

    def _unclaim_one_unit(self, product, package_id=False):
        """Remove one picked unit of ``product`` from one package.

        The quantity is decremented (not the whole line reset) so a row
        holding several units keeps the rest; the line is only unpicked
        once nothing is left. Returns the written line, or an empty
        recordset when the package holds no picked unit.
        """
        self.ensure_one()
        lines = self.picking_id.move_ids.filtered(
            lambda move: (
                move.product_id == product
                and move.state not in ("done", "cancel")
            )
        ).move_line_ids.filtered(
            lambda line: (
                line.picked
                and (line.result_package_id.id or False) == (package_id or False)
            )
        ).sorted(lambda line: line.id)
        if not lines:
            return self.env["stock.move.line"]
        line = lines[-1]
        rounding = product.uom_id.rounding
        remaining = line.quantity - 1.0
        if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
            line.write({"quantity": 0.0, "picked": False})
        else:
            line.quantity = remaining
        return line

    def _unclaim_scanned_product(self, product):
        """Unclaim one unit of a scanned quantity-tracked product.

        One scan removes exactly one picked unit (the +1 shortcut in
        reverse). When those units sit in several packages nothing is
        written: the package chooser is filled instead, and
        :meth:`action_unclaim_unit` applies the operator's choice.
        """
        self.ensure_one()
        groups = self._get_unclaim_groups(product)
        if not groups:
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no picked line to unclaim.",
                    label=product.display_name,
                ),
            )
            return True
        if len(groups) == 1:
            self._unclaim_one_unit(product, groups[0]["package_id"])
            self.unclaim_product_id = False
            self.unclaim_choices = []
            self._set_message(
                "success",
                self.env._(
                    "Unclaimed 1 unit of %(prod)s.",
                    prod=product.display_name,
                ),
            )
            return True
        self.unclaim_product_id = product
        self.unclaim_choices = groups
        self._set_message(
            "more_match",
            self.env._(
                "%(prod)s is picked in several packages. Choose the package "
                "to unclaim.",
                prod=product.display_name,
            ),
        )
        return True

    def _unclaim_scanned_lot(self, lot):
        """Cancel one unit of a scanned batch (lot).

        Scanning a lot identifies the batch; the operator asked for a
        per-scan decrement, so one unit is removed from the batch's picked
        lines instead of unpicking the whole line. Serial numbers are
        1 unit per line and keep the whole-line path.
        """
        self.ensure_one()
        lines = self.picking_id.move_ids.filtered(
            lambda move: (
                move.product_id == lot.product_id
                and move.state not in ("done", "cancel")
            )
        ).move_line_ids.filtered(
            lambda line: line.picked and line.lot_id == lot
        ).sorted(lambda line: line.id)
        if not lines:
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no picked line to unclaim.",
                    label=lot.name,
                ),
            )
            return True
        line = lines[-1]
        remaining = line.quantity - 1.0
        if float_compare(
            remaining, 0.0,
            precision_rounding=lot.product_id.uom_id.rounding,
        ) <= 0:
            line.write({"quantity": 0.0, "picked": False})
        else:
            line.quantity = remaining
        self._set_message(
            "success",
            self.env._("Unclaimed 1 unit of %(prod)s.", prod=lot.name),
        )
        return True

    def action_unclaim_unit(self, product_id, package_id=False):
        """Apply the package choice of the unclaim dialog."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            self._set_message("error", self.env._("Product not found."))
            return False
        line = self._unclaim_one_unit(product, package_id or False)
        self.unclaim_product_id = False
        self.unclaim_choices = []
        if not line:
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no picked line to unclaim.",
                    label=product.display_name,
                ),
            )
            return True
        self._set_message(
            "success",
            self.env._(
                "Unclaimed 1 unit of %(prod)s.",
                prod=product.display_name,
            ),
        )
        return True

    def _split_one_unit(self, product, package_id=False):
        """Move one picked unit of ``product`` out of one package.

        The packed line keeps the rest of its quantity and a loose picked
        line receives the split unit (created when none exists), so the
        picked total is unchanged — only the package attachment moves.
        """
        self.ensure_one()
        packed_lines = self.picking_id.move_ids.filtered(
            lambda move: (
                move.product_id == product
                and move.state not in ("done", "cancel")
            )
        ).move_line_ids.filtered(
            lambda line: (
                line.picked
                and (line.result_package_id.id or False) == (package_id or False)
            )
        ).sorted(lambda line: line.id)
        if not packed_lines:
            return self.env["stock.move.line"]
        line = packed_lines[-1]
        rounding = product.uom_id.rounding
        remaining = line.quantity - 1.0
        if float_compare(remaining, 0.0, precision_rounding=rounding) <= 0:
            # The package held exactly one unit: keep the (now empty)
            # line for the row but detach it from the package.
            line.write({
                "quantity": 0.0,
                "picked": False,
                "result_package_id": False,
            })
        else:
            line.quantity = remaining
        loose_line = line.move_id.move_line_ids.filtered(
            lambda candidate: (
                candidate.picked
                and not candidate.result_package_id
                and candidate.id != line.id
                and candidate.location_id == line.location_id
            )
        )[:1]
        if loose_line:
            loose_line.quantity = loose_line.quantity + 1.0
        else:
            loose_line = self.env["stock.move.line"].create({
                "move_id": line.move_id.id,
                "picking_id": line.picking_id.id,
                "product_id": product.id,
                "product_uom_id": line.product_uom_id.id,
                "location_id": line.location_id.id,
                "location_dest_id": line.location_dest_id.id,
                "quantity": 1.0,
                "picked": True,
                "result_package_id": False,
            })
        return loose_line

    def _split_scanned_product(self, product):
        """Split one unit of a scanned quantity-tracked product.

        One scan moves exactly one picked unit out of its package. When
        those units sit in several packages nothing is written: the
        package chooser is filled instead, and
        :meth:`action_split_unit` applies the operator's choice.
        """
        self.ensure_one()
        groups = self._get_unclaim_groups(product, require_package=True)
        if not groups:
            self.unclaim_product_id = False
            self.unclaim_choices = []
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no package to remove.",
                    label=product.display_name,
                ),
            )
            return True
        if len(groups) == 1:
            self._split_one_unit(product, groups[0]["package_id"])
            self.unclaim_product_id = False
            self.unclaim_choices = []
            self._set_message(
                "success",
                self.env._(
                    "Split 1 unit of %(prod)s out of its package.",
                    prod=product.display_name,
                ),
            )
            return True
        self.unclaim_product_id = product
        self.unclaim_choices = groups
        self._set_message(
            "more_match",
            self.env._(
                "%(prod)s is packed in several packages. Choose the package "
                "to split from.",
                prod=product.display_name,
            ),
        )
        return True

    def action_split_unit(self, product_id, package_id=False):
        """Apply the package choice of the split (remove from pack) dialog."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            self._set_message("error", self.env._("Product not found."))
            return False
        line = self._split_one_unit(product, package_id or False)
        self.unclaim_product_id = False
        self.unclaim_choices = []
        if not line:
            self._set_message(
                "info",
                self.env._(
                    "%(label)s has no package to remove.",
                    label=product.display_name,
                ),
            )
            return True
        self._set_message(
            "success",
            self.env._(
                "Split 1 unit of %(prod)s out of its package.",
                prod=product.display_name,
            ),
        )
        return True

    def action_cancel_unclaim(self):
        """Close the unclaim/split package chooser without writing."""
        self.ensure_one()
        self.unclaim_product_id = False
        self.unclaim_choices = []
        if (self.scan_mode or "default") == "split_scan":
            self._set_message("info", self.env._("Split cancelled."))
        else:
            self._set_message("info", self.env._("Unclaim cancelled."))
        return True

    def action_clear_pack_intent(self):
        """Drop the pack intent without scanning anything."""
        self.ensure_one()
        self.scan_mode = "default"
        return True

    def action_confirm_cross_order_pick(self):
        """Pick the serial anyway, releasing the other transfer's reservation.

        Confirming mirrors native Odoo: core frees the other transfer's
        reservation while validating this line.
        """
        self.ensure_one()
        if not self.cross_order_pending:
            self._set_message(
                "error", self.env._("Nothing to confirm for this scan.")
            )
            return False
        self.cross_order_pending = False
        # The operator scanned only the serial (no product scan), so the
        # wizard product may still be empty and the demand check would
        # compare against 0. Derive both from the scanned lot.
        if self.lot_id:
            self.product_id = self.lot_id.product_id.id
            self.lot_name = self.lot_id.name
            if not self.product_qty or self.product_qty <= 0:
                self.product_qty = 1.0
        lot_quants = self._compute_qty_available()
        forced = self.with_context(force_cross_order=True)
        in_transfer = self.picking_id.move_ids.filtered(
            lambda move: move.product_id == self.product_id
            and move.state != "cancel"
        )
        if in_transfer:
            return forced.action_confirm(lot_quants=lot_quants)
        return forced._confirm_new_product_lot(lot_quants=lot_quants)

    def action_split_package(
        self,
        package_id,
        line_ids,
        dest_mode="new",
        dest_package_id=False,
        dest_package_name=False,
    ):
        """Split whole lines out of a package (R1-R4 of the v3 design).

        The lines stop going into ``package`` and start going into the
        destination package (or loose). Only ``result_package_id`` moves:
        the source quant/package is reconciled by core at validation, so
        nothing physical is rewritten here. Picked lines are reset so the
        operator re-scans them under the new package.

        :param dest_mode: "new" (create), "loose" (no package) or
            "existing" (``dest_package_id``).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        package = self.env["stock.package"].browse(package_id)
        if not package.exists():
            self._set_message("error", self.env._("Package not found."))
            return False
        lines = self.env["stock.move.line"].browse(line_ids).exists()
        if not lines:
            self._set_message(
                "error", self.env._("Select at least one line to split.")
            )
            return False
        # R1: never touch another transfer's goods.
        if lines.filtered(lambda line: line.picking_id != self.picking_id):
            self._set_message(
                "error",
                self.env._(
                    "Only products of this transfer can be split out of a "
                    "package."
                ),
            )
            return False
        in_package = lines.filtered(
            lambda line: package in (line.package_id | line.result_package_id)
        )
        if not in_package:
            self._set_message(
                "error",
                self.env._(
                    "None of the selected lines is in package %(pkg)s.",
                    pkg=package.name,
                ),
            )
            return False
        # R2: destination.
        if dest_mode == "existing":
            dest = self.env["stock.package"].browse(dest_package_id)
            if not dest.exists():
                self._set_message(
                    "error", self.env._("Destination package not found.")
                )
                return False
        elif dest_mode == "new":
            name = dest_package_name or self.env._(
                "SPLIT-%(pkg)s", pkg=package.name
            )
            dest = self.env["stock.package"].create({"name": name})
        else:
            dest = self.env["stock.package"]
        # R4: split lines go back to "not picked" so they are re-scanned.
        reset_picked = in_package.filtered("picked")
        in_package.write({
            "result_package_id": dest.id or False,
            "picked": False,
        })
        # R3: report when the source package no longer holds this
        # transfer's lines.
        # "Empty" means: this transfer no longer ships anything through
        # the package. Source provenance (package_id) is left untouched.
        remaining = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("result_package_id", "=", package.id),
        ])
        dest_label = dest.name if dest else self.env._("loose products")
        self._set_message(
            "success",
            self.env._(
                "Split %(count)s line(s) from %(pkg)s to %(dest)s."
                "%(empty)s%(picked)s",
                count=len(in_package),
                pkg=package.name,
                dest=dest_label,
                empty=self.env._(" Package %(pkg)s is now empty.", pkg=package.name)
                if not remaining
                else "",
                picked=self.env._(" %(count)s line(s) reset to not picked.",
                                  count=len(reset_picked))
                if reset_picked
                else "",
            ),
        )
        return True

    def action_undo_package_scan(self, package_id):
        """Undo a whole-package pick: picked back to False, package cleared."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        lines = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("picked", "=", True),
            "|",
            ("package_id", "=", package_id),
            ("result_package_id", "=", package_id),
        ])
        if not lines:
            self._set_message(
                "info", self.env._("Nothing to undo in this package.")
            )
            return True
        lines.write({"picked": False, "result_package_id": False})
        self._set_message(
            "info",
            self.env._(
                "Package scan undone: %(count)s line(s).", count=len(lines)
            ),
        )
        return True


    def _bind_to_package(self, package):
        """Bind all picked-but-unpacked move lines to ``package``."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        # Use a fresh search instead of self.picking_id.move_line_ids to
        # avoid stale cached values of the stored+computed ``picked``
        # field. picked=True is the source of truth for scanned lines.
        all_lines = self.env["stock.move.line"].search([
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
            ("picked", "=", True),
        ])
        unpacked = all_lines.filtered(lambda l: not l.result_package_id)
        if not unpacked:
            self._set_message(
                "info",
                self.env._("No unpacked picked products to bind."),
            )
            return True
        unpacked.write({"picked": True})
        unpacked.result_package_id = package.id
        self._set_message(
            "success",
            self.env._("Products bound to package %s.", package.name),
        )
        return True

    def _get_new_product_policy(self):
        """Return how lots/serials of products outside the transfer are handled."""
        self.ensure_one()
        if self.allow_new_products:
            return "allow"
        return (
            self.picking_id.picking_type_id.barcode_new_product_policy
            or "forbid"
        )

    def _scan_new_product_lot(self, lot, product):
        """Let a unique existing lot/serial supersede the current scan context."""
        # The operator explicitly scanned a different product's lot/serial.
        # Drop unconfirmed input and stale confirmations before binding the
        # newly identified product.
        self.visible_force_done = False
        self.visible_force_add = False
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.active_move_id = False
        self.lot_id = lot
        self.lot_name = lot.name
        self.product_qty = 1.0
        lot_quants = self._compute_qty_available()
        error = self._get_lot_pick_error(lot, quants=lot_quants)
        if error:
            self._set_message(
                "more_match" if self.cross_order_pending else "error", error
            )
            return True
        if self._get_new_product_policy() == "warn":
            # Only wizard state is written before confirmation. The stock
            # move and move line are created by action_confirm_new_product.
            self.visible_force_add = True
            self._set_message(
                "more_match",
                self.env._(
                    "Lot/serial number %(sn)s belongs to product %(product)s, "
                    "which is not in transfer %(picking)s. Confirm adding "
                    "1 unit and picking it.",
                    sn=lot.name,
                    product=product.name,
                    picking=self.picking_id.name,
                ),
            )
            return True
        return self._confirm_new_product_lot(lot_quants=lot_quants)

    def _confirm_new_product_lot(self, lot_quants=None):
        """Validate and add the prepared outside product and its lot/serial."""
        self.ensure_one()
        product = self.product_id
        lot = self.lot_id
        if (
            not product
            or product.tracking not in ("lot", "serial")
            or not lot
            or lot.product_id != product
        ):
            self._set_message(
                "error", self.env._("No product addition is awaiting confirmation.")
            )
            return False
        component_moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if component_moves:
            self._set_message(
                "error",
                self.env._(
                    "Product %(name)s is already part of this transfer",
                    name=product.name,
                ),
            )
            return False
        error = self._get_lot_pick_error(lot, quants=lot_quants)
        if error:
            self._set_message(
                "more_match" if self.cross_order_pending else "error", error
            )
            return False
        result = self.with_context(
            allow_new_product_lot=True
        ).action_confirm(lot_quants=lot_quants)
        if not result:
            return False
        if self.allow_new_products:
            if self.picking_id.state == "draft":
                # The picking was empty when created from the workbench; now
                # that it has a move it can be confirmed like a regular one.
                self.picking_id.action_confirm()
            # Confirming the new move may reserve the same lot again; keep
            # only the line the operator just picked.
            self.picking_id.invalidate_recordset(["move_line_ids", "move_ids"])
            duplicates = self.picking_id.move_line_ids.filtered(
                lambda line: (
                    not line.picked
                    and line.product_id == product
                    and line.lot_id == lot
                )
            )
            duplicates.unlink()
        self._set_message(
            "success",
            self.env._(
                "Added product %(product)s with demand 1 and picked "
                "lot/serial number %(sn)s.",
                product=product.name,
                sn=lot.name,
            ),
        )
        return result

    def action_confirm_new_product(self):
        """RPC confirmation for the outside-product warning."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if (
            not self.visible_force_add
            or self._get_new_product_policy() == "forbid"
        ):
            self.visible_force_add = False
            self._set_message(
                "error", self.env._("No product addition is awaiting confirmation.")
            )
            return False
        if self.product_id and self.product_id.tracking == "none":
            # Quantity-tracked outside product: add one unit and pick it.
            return self.action_force_add(product_id=self.product_id.id)
        return self._confirm_new_product_lot()

    def action_cancel_new_product(self):
        """Discard the outside-product preview without changing the picking."""
        self.ensure_one()
        self._clean_values()
        return True

    def _resolve_lot_owner(self, lot, product):
        """Identify whether ``product`` belongs to this picking.

        Products already on the transfer follow the normal scan flow. A
        unique existing lot/serial takes priority over the current scan
        context; an outside product is then handled by its picking-type
        policy.
        """
        self.ensure_one()
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return True
        component_moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if component_moves:
            self.product_id = product
            # Follow the scanned product: highlight its move so the
            # operator keeps scanning it without re-selecting the row.
            if not self.active_move_id or self.active_move_id.product_id != product:
                self.active_move_id = component_moves[:1]
            self.product_uom_id = product.uom_id
            if lot:
                self.lot_id = lot
                self.lot_name = lot.name
                lot_quants = self._compute_qty_available()
                if product.tracking == "serial":
                    self.product_qty = 1.0
                    # Keep the error set by action_confirm (e.g. serial
                    # not in the scanned location) instead of replacing
                    # it with the generic step instruction.
                    if not self.action_confirm(lot_quants=lot_quants):
                        return True
                    self._set_message_step()
                    self._set_message(
                        "success",
                        self.env._("Matched product %(product)s for serial number "
                          "%(sn)s. It has been added.",
                          product=product.name,
                          sn=lot.name),
                    )
                    return True
                self._confirm_scanned_lot(lot_quants=lot_quants)
                return True
            else:
                self.lot_id = False
                self.lot_name = False
                if product.tracking != "none":
                    self._set_message(
                        "info", self.env._("Product: %s. Scan lot.", product.name)
                    )
                    self.step = self._step_index("lot")
                else:
                    self._set_message(
                        "info",
                        self.env._("Product: %s. Enter qty and confirm.", product.name),
                    )
                    self.step = self._step_index("qty")
            self._set_message_step()
            return True
        if (
            lot
            and product.tracking in ("lot", "serial")
            and self._get_new_product_policy() != "forbid"
        ):
            return self._scan_new_product_lot(lot, product)
        self._set_message(
            "error",
            self.env._("Lot belongs to product %(name)s which is not part of this transfer", **{"name": product.name}),
        )
        return True

    def _create_new_lot(self):
        if not self.lot_name or not self.product_id:
            return False
        existing = self.env["stock.lot"].search([
            ("name", "=", self.lot_name),
            ("product_id", "=", self.product_id.id),
        ])
        if existing:
            return existing
        return self.env["stock.lot"].create({
            "name": self.lot_name,
            "product_id": self.product_id.id,
            "company_id": self.company_id.id if self.company_id else self.env.company.id,
        })

    def _compute_qty_available(self):
        """Set ``qty_available`` and return the quants that were read.

        The returned recordset lets the serial confirm path
        (``_get_lot_pick_error``) reuse the same read instead of
        querying the lot's quants a second time.
        """
        self.qty_available = 0.0
        if not self.product_id or not self.location_id:
            return self.env["stock.quant"]
        if self.lot_id:
            quants = self.env["stock.quant"].search([
                ("product_id", "=", self.product_id.id),
                ("lot_id", "=", self.lot_id.id),
            ])
            self.qty_available = sum(
                q.quantity for q in quants
                if q.location_id == self.location_id
            )
            return quants
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.product_id.id),
            ("location_id", "=", self.location_id.id),
        ])
        # Barcode scenario: at most a handful of quants for one product +
        # location. search+mapped is clearer than the Odoo 19 _read_group
        # tuple format and avoids the deprecated read_group API.
        self.qty_available = sum(quants.mapped("quantity"))
        return quants

    def _get_lot_quants(self, lot, quants=None):
        """Positive quants of ``lot``, reusing ``quants`` when provided."""
        if quants is None:
            quants = self.env["stock.quant"].search([
                ("product_id", "=", lot.product_id.id),
                ("lot_id", "=", lot.id),
            ])
        return quants.filtered(lambda q: q.quantity > 0)

    # --- Action methods ---
    def _get_lot_pick_error(self, lot, quants=None):
        """Return why ``lot`` cannot be picked from the scanned source.

        Outgoing and internal transfers require an existing lot/serial to be
        physically in the scanned source location. Supplier receipts are
        exempt: their lots are arriving from the supplier, so an existing lot
        legitimately may have no quant at the vendor location. Customer
        returns are incoming transfers too, but must have the lot at the
        customer source location.

        Returning the reason at scan time avoids core's validation-time
        error, which reports a single serial per attempt and forces a
        back-and-forth cleanup loop.

        :return: translated error message, or False when the lot/serial can
            be picked.
        """
        self.ensure_one()
        tracking = lot.product_id.tracking
        if not self.picking_id or tracking not in ("lot", "serial"):
            return False
        location = self.location_id
        if not location:
            move = self.active_move_id or self.picking_id.move_ids.filtered(
                lambda m: m.product_id == lot.product_id and m.state != "cancel"
            )[:1]
            location = move.location_id if move else self.picking_id.location_id
        if not location:
            return False
        quants = self._get_lot_quants(lot, quants=quants)
        is_customer_return = (
            self.picking_type_code == "incoming"
            and bool(self.picking_id.return_id)
        )
        if tracking == "serial" and self.picking_type_code != "incoming":
            # Already delivered: sending it again would create a second unit
            # of the same serial at the customer location. A customer return
            # legitimately starts there, so this guard excludes all incoming.
            if quants.filtered(lambda q: q.location_id.usage == "customer"):
                return self.env._(
                    "Serial number %(sn)s has already been delivered and "
                    "cannot be picked again.",
                    sn=lot.name,
                )
        if self.picking_type_code != "incoming" or is_customer_return:
            in_source = quants.filtered(
                lambda q: q.location_id.parent_path.startswith(
                    location.parent_path
                )
            )
            if not in_source:
                if quants:
                    return self.env._(
                        "Lot/serial number %(sn)s is not in location "
                        "%(location)s (currently in: %(locations)s). It was "
                        "not added to this transfer.",
                        sn=lot.name,
                        location=location.display_name,
                        locations=", ".join(
                            quants.mapped("location_id.display_name")
                        ),
                    )
                return self.env._(
                    "Lot/serial number %(sn)s has no stock in location "
                    "%(location)s. It was not added to this transfer.",
                    sn=lot.name,
                    location=location.display_name,
                )
            if tracking == "lot":
                required = self.product_qty or 1.0
                available = sum(in_source.mapped("available_quantity"))
                if float_compare(
                    available,
                    required,
                    precision_rounding=lot.product_id.uom_id.rounding,
                ) < 0:
                    return self.env._(
                        "Insufficient unreserved stock for lot %(sn)s in "
                        "location %(location)s (available: %(available)s, "
                        "required: %(required)s).",
                        sn=lot.name,
                        location=location.display_name,
                        available=available,
                        required=required,
                    )
        if tracking == "serial":
            # Reserved by another transfer: picking it here would move stock
            # promised elsewhere (core reports this only at validation).
            other_lines = self.env["stock.move.line"].search([
                ("picking_id", "!=", self.picking_id.id),
                ("picking_id", "!=", False),
                ("product_id", "=", lot.product_id.id),
                ("lot_id", "=", lot.id),
                ("state", "not in", ("done", "cancel")),
            ])
            if other_lines:
                pickings = ", ".join(other_lines.picking_id.mapped("name"))
                policy = self._get_cross_order_policy()
                forced = bool(self.env.context.get("force_cross_order"))
                if policy == "allow" or (policy == "warn" and forced):
                    self.cross_order_pending = False
                    return False
                if policy == "warn":
                    self.cross_order_pending = True
                    return self.env._(
                        "Serial number %(sn)s is still reserved by another "
                        "transfer (%(pickings)s). Confirm to pick it anyway: "
                        "its reservation there will be released.",
                        sn=lot.name,
                        pickings=pickings,
                    )
                self.cross_order_pending = False
                return self.env._(
                    "Serial number %(sn)s is reserved by another transfer "
                    "(%(pickings)s) and cannot be picked again.",
                    sn=lot.name,
                    pickings=pickings,
                )
        return False

    def _confirm_scanned_lot(self, lot_quants=None):
        """Immediately add one to the picked quantity of the scanned lot.

        ``_process_stock_move_line`` uses SET semantics, so the target
        quantity must include what was already picked for this lot in the
        unpacked group. Packed lines are sealed from normal scans; only an
        explicit move-line edit can change them. Other lots of the same
        product keep their own picked move lines.
        """
        self.ensure_one()
        lot_name = self.lot_id.name or self.lot_name
        picked_qty = 0.0
        if self.lot_id:
            picked_qty = sum(
                line.quantity
                for line in self.picking_id.move_line_ids
                if line.picked
                and not line.result_package_id
                and line.lot_id == self.lot_id
                and line.product_id == self.product_id
                and (not self.location_id or line.location_id == self.location_id)
            )
        self.product_qty = picked_qty + 1.0
        quantity = self.product_qty
        self.step = self._step_index("qty")
        result = self.action_confirm(lot_quants=lot_quants)
        if result:
            self._set_message(
                "success",
                self.env._(
                    "Lot: %(lot)s. Picked quantity: %(qty)s. "
                    "Scan again to add 1.",
                    lot=lot_name,
                    qty=quantity,
                ),
            )
        return result

    def action_confirm(self, lot_quants=None):
        """Confirm the scanned product and update stock move lines.

        :param lot_quants: quants of the scanned lot already read during
            the scan (``_compute_qty_available``); avoids a second
            quant query on the serial validation path.
        """
        if not self._check_selector_resolved():
            return False
        if self.picking_state == "draft" and not self.allow_new_products:
            self._set_message(
                "error", self.env._("Transfer is draft, confirm it before scanning")
            )
            return False
        if self.picking_state in ("done", "cancel"):
            self._set_message(
                "error",
                self.env._("Transfer is %(state)s, cannot scan", **{"state": self.picking_state}),
            )
            return False
        if not self.product_id:
            self._set_message("error", self.env._("No product scanned"))
            return False
        if not self.location_id:
            self._set_message("error", self.env._("No source location scanned"))
            return False
        if self.barcode_scan_dest_location and not self.location_dest_id:
            self._set_message(
                "error", self.env._("No destination location scanned")
            )
            return False
        if self.product_id.tracking != "none" and not self.lot_id and not self.lot_name:
            self._set_message("error", self.env._("Lot required for tracked product"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False

        # A pre-existing serial must physically be in the scanned source
        # location. This catches wrong/past serials at scan time instead
        # of at validation, where core reports one serial per attempt and
        # forces the operator to go back and delete it manually. Run this
        # before the duplicate check so an already-added bad line still
        # reports the source-location problem that must be corrected.
        # Serials created on the fly (use_create_lots) are exempt: whether
        # creating them is allowed is decided by the operation type.
        new_lot = not self.lot_id and bool(self.lot_name)
        if (
            not new_lot
            and self.product_id.tracking == "serial"
            and self.lot_id
        ):
            error = self._get_lot_pick_error(self.lot_id, quants=lot_quants)
            if error:
                self._set_message(
                    "more_match" if self.cross_order_pending else "error", error
                )
                return False

        # A serial can only be picked once per transfer. Without this the
        # second scan silently matches the existing picked line and
        # reports success, so the operator cannot tell the scan was
        # ignored.
        if self.product_id.tracking == "serial" and self.lot_id:
            already_picked = self.picking_id.move_line_ids.filtered(
                lambda l: l.picked and l.lot_id == self.lot_id
            )
            if already_picked:
                self._set_message(
                    "error",
                    self.env._("Serial number %(sn)s has already been added to this "
                      "transfer. Do not scan it again.",
                      sn=self.lot_id.name),
                )
                return False

        if not self.lot_id and self.lot_name and self.product_id.tracking != "none":
            self.lot_id = self._create_new_lot()

        if self.env.context.get("allow_new_product_lot"):
            component_moves = self.picking_id.move_ids.filtered(
                lambda m: m.product_id == self.product_id and m.state != "cancel"
            )
            if not component_moves:
                # All scan, location and serial safety checks above have
                # passed. Only now is it safe to create business records.
                self.active_move_id = self._create_picking_move(
                    self.product_id, self.product_qty
                )

        move_dic = self._process_stock_move_line()
        if move_dic:
            product_name = self.product_id.name
            quantity = self.product_qty
            excess = (
                self._get_over_picked_qty(self.product_id)
                if self._get_excess_qty_policy() == "allow"
                else 0.0
            )
            # _clean_values resets the banner to the next step instruction
            # and clears product_id, so values must be captured first and
            # the over-demand notice set AFTER it.
            self._clean_values()
            if excess:
                self._set_message(
                    "success",
                    self.env._("Product scanned: %(prod)s x%(qty)s (over demand by "
                      "%(excess)s)",
                      prod=product_name,
                      qty=quantity,
                      excess=excess),
                )
            return move_dic
        return False

    def _get_over_picked_qty(self, product):
        """Return how much this product is picked above its demand.

        Only used to mention the excess in the success message when the
        operation type allows over-picking; 0 elsewhere.
        """
        self.ensure_one()
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        demand = sum(m.product_uom_qty for m in moves)
        picked = sum(
            line.quantity
            for line in moves.move_line_ids
            if line.picked and line.product_id == product
        )
        return max(0.0, picked - demand)

    def _default_scan_mode(self):
        """Pick the scan mode that fits the transfer direction.

        Receipts (incoming) build packages while scanning: the operator
        scans the products first, then puts them into a package, so the
        default mode there is "pack". Deliveries and internal transfers
        move goods that are already packed, so they start in "default"
        (a package barcode picks the whole package).
        """
        self.ensure_one()
        if self.picking_id and self.picking_id.picking_type_code == "incoming":
            return "pack"
        return "default"

    @api.depends("scan_mode")
    def _compute_package_scan_intent(self):
        """Mirror scan_mode for the pre-v4 client action."""
        for rec in self:
            rec.package_scan_intent = (
                "pack" if rec.scan_mode == "pack" else "take"
            )

    def _get_cross_order_policy(self):
        """Return how a serial reserved by another transfer is handled."""
        self.ensure_one()
        return (
            self.picking_id.picking_type_id.barcode_cross_order_policy
            or "warn"
        )

    def _get_excess_qty_policy(self):
        """Return the over-picking policy of the transfer's operation type.

        Falls back to ``warn`` (legacy behaviour) when no picking type is
        available, e.g. when the wizard is opened without a transfer.
        """
        self.ensure_one()
        return (
            self.picking_id.picking_type_id.barcode_excess_qty_policy
            or "warn"
        )

    def _process_stock_move_line(self):
        """Find matching picking move and update/create move line.

        SET semantics (not ADD): matching line quantity is replaced.
        Allowed over-picking preserves other lots; forced warned over-picking
        redistributes demand from other unpacked lines for lot substitution.

        picked write: every created/updated line gets picked=True.
        move.picked is NOT set explicitly — it is computed from
        move_line_ids.picked. Setting move.picked directly triggers
        _inverse_picked, which marks ALL lines of the move as picked
        (wrong for serial products picked one-by-one).
        """
        self.ensure_one()
        if not self.picking_id:
            return False
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state != "cancel"
        )
        if not moves:
            self._set_message(
                "error",
                self.env._("Product %(name)s is not part of this transfer", **{"name": self.product_id.name}),
            )
            return False

        # Read the moves' lines once; every filtered/compare below works on
        # this recordset (mapped() re-read the same lines three times).
        # Normal scans only target unpacked lines. Packed quantities still
        # count toward demand below, but can only be changed by the explicit
        # move-line edit/delete actions.
        all_lines = moves.move_line_ids
        existing_lines = all_lines.filtered(
            lambda l: (
                l.product_id == self.product_id
                and not l.result_package_id
                and (not self.location_id or l.location_id == self.location_id)
                and (not self.lot_id or l.lot_id == self.lot_id)
            )
        )
        # A freshly confirmed move (empty transfer created from the
        # workbench) may already reserve the scanned serial on another
        # source sub-location. Reuse that unpicked line instead of creating
        # a second one for the same serial.
        if (
            not existing_lines
            and self.product_id.tracking == "serial"
            and self.lot_id
        ):
            existing_lines = all_lines.filtered(
                lambda l: (
                    l.product_id == self.product_id
                    and not l.result_package_id
                    and not l.picked
                    and l.lot_id == self.lot_id
                )
            )
        # For serial-tracked products on receptions, Odoo pre-creates
        # placeholder lines (one per unit) with quantity set but no lot
        # and picked=False. When scanning a serial, no line matches by
        # lot, so reuse the first unpicked, unpacked placeholder instead of
        # creating a new line (which would exceed demand).
        if (
            not existing_lines
            and self.product_id.tracking == "serial"
            and self.lot_id
        ):
            existing_lines = all_lines.filtered(
                lambda l: (
                    l.product_id == self.product_id
                    and not l.result_package_id
                    and (not self.location_id or l.location_id == self.location_id)
                    and not l.lot_id
                    and not l.picked
                )
            )
        other_lines = all_lines - existing_lines
        # Only already-picked lines count against demand. Pre-filled
        # reception lines (quantity set, picked=False) must not block
        # scanning.
        other_lines_qty = sum(l.quantity for l in other_lines if l.picked)
        total_demand = sum(m.product_uom_qty for m in moves)
        force = self.env.context.get("force_create_move", False)
        policy = self._get_excess_qty_policy()
        rounding = self.product_id.uom_id.rounding

        move_lines_dic = {}

        if existing_lines:
            max_quantity = total_demand - other_lines_qty
            if (
                float_compare(self.product_qty, max_quantity,
                              precision_rounding=rounding) > 0
                and not force
            ):
                if policy == "forbid":
                    self._set_message(
                        "error",
                        self.env._("Quantity exceeds demand (max: %(max)s). "
                          "Over-picking is forbidden for this operation "
                          "type.",
                          max=max_quantity),
                    )
                    return False
                if policy == "warn":
                    self._set_message(
                        "more_match",
                        self.env._("Quantity exceeds demand (max: %s)", max_quantity),
                    )
                    self.visible_force_done = True
                    return False
            line = existing_lines[:1]
            increase = self.product_qty - line.quantity
            if increase > 0:
                for extra in (existing_lines - line):
                    take = min(extra.quantity, increase)
                    extra.quantity = extra.quantity - take
                    increase -= take
                    if float_is_zero(extra.quantity,
                                     precision_rounding=rounding):
                        extra.unlink()
                    if increase <= 0:
                        break
            line.quantity = self.product_qty
            line.picked = True
            if self.lot_id and not line.lot_id:
                line.lot_id = self.lot_id.id
                line.lot_name = self.lot_id.name
            # NOTE: do NOT set line.move_id.picked here. move.picked is
            # computed from move_line_ids.picked; setting it explicitly
            # triggers _inverse_picked which marks ALL lines of the move
            # as picked — wrong for serial products where each serial is
            # picked individually.
            move_lines_dic[line.move_id.id] = line
        else:
            is_serial = self.product_id.tracking == "serial"
            excess = other_lines_qty + self.product_qty - total_demand
            # Decide before redistributing other lines: redistributing and
            # then aborting would leave those lines emptied even though the
            # scan was rejected.
            if excess > 0 and not force:
                if policy == "forbid":
                    self._set_message(
                        "error",
                        self.env._("Quantity exceeds demand (max: %(max)s). "
                          "Over-picking is forbidden for this operation "
                          "type.",
                          max=total_demand),
                    )
                    return False
                if policy == "warn":
                    self._set_message(
                        "more_match",
                        self.env._("Quantity exceeds demand (max: %s)", total_demand),
                    )
                    self.visible_force_done = True
                    return False
            if excess > 0 and policy != "allow":
                # Allowed over-picking preserves other lots. Forced warned
                # over-picking may consume unpacked lines only. A packed line
                # still counts in other_lines_qty, but taking quantity from it
                # would silently change the package contents.
                redistributable = other_lines.filtered(
                    lambda l: not l.result_package_id
                )
                for line in redistributable.sorted(key=lambda l: l.id):
                    if is_serial and line.quantity > 0:
                        continue
                    take = min(line.quantity, excess)
                    line.quantity = line.quantity - take
                    excess -= take
                    if float_is_zero(line.quantity,
                                     precision_rounding=rounding):
                        line.unlink()
                    if excess <= 0:
                        break
            move = moves[:1]
            sml_vals = {
                "move_id": move.id,
                "picking_id": self.picking_id.id,
                "product_id": self.product_id.id,
                "product_uom_id": move.product_uom.id or self.product_id.uom_id.id,
                "quantity": self.product_qty,
                "picked": True,
                "location_id": self.location_id.id,
                "location_dest_id": (
                    self.location_dest_id.id
                    if self.location_dest_id
                    else move.location_dest_id.id
                ),
                "lot_id": self.lot_id.id if self.lot_id else False,
                "lot_name": self.lot_id.name if self.lot_id else self.lot_name or False,
                "result_package_id": False,
            }
            new_line = self.env["stock.move.line"].create(sml_vals)
            # move.picked auto-computes from new_line.picked (see note above).
            move_lines_dic[move.id] = new_line

        return move_lines_dic

    def action_force_done(self):
        """Confirm the over-demand scan.

        Refused when the operation type forbids over-picking, so a stale
        button or a direct RPC call cannot bypass the policy.

        Two pending flows land here:
          - a row quantity add blocked by the 'warn' policy
            (``pending_add``): re-apply the exact row target with force;
          - the legacy scan flow (``visible_force_done`` without
            ``pending_add``): confirm the scanned quantity.
        """
        self.ensure_one()
        if self._get_excess_qty_policy() == "forbid":
            self._set_message(
                "error",
                self.env._("Over-picking is forbidden for this operation type."),
            )
            self.visible_force_done = False
            self.pending_add = False
            return False
        if self.pending_add:
            return self._apply_pending_add()
        return self.with_context(force_create_move=True).action_confirm()

    def _apply_pending_add(self):
        """Apply the row quantity add blocked by the 'warn' policy."""
        self.ensure_one()
        pending = self.pending_add or {}
        self.pending_add = False
        self.visible_force_done = False
        move = self.picking_id.move_ids.filtered(
            lambda candidate: candidate.id == pending.get("move_id")
        )
        if not move:
            self._set_message("error", self.env._("Line not found."))
            return False
        if not self.set_active_move(move.id):
            return False
        return self._set_untracked_move_qty(
            move,
            float(pending.get("qty") or 0.0),
            pending.get("package_id") or False,
            force=True,
        )

    def action_consume_by_demand(self):
        """One-click consume the full demand of the active/non-tracked
        product.

        Tracked products (serial + lot) are rejected — lot/serial picking
        requires scanning each lot. Only non-tracked products can be
        consumed by demand. The demand is move.product_uom_qty (the full
        requested quantity, independent of reservation).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        product = self.product_id or (
            self.active_move_id.product_id if self.active_move_id else False
        )
        if not product:
            self._set_message("error", self.env._("No product selected"))
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                self.env._("Cannot consume tracked product by demand; scan the lot"),
            )
            return False
        # Full demand from the move (not reservation)
        move = self.active_move_id or self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state not in ("done", "cancel")
        )[:1]
        if not move:
            self._set_message(
                "error",
                self.env._("Product %s is not part of this transfer", product.name),
            )
            return False
        if not self.location_id:
            self._set_message("error", self.env._("No source location scanned"))
            return False
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.active_move_id = move
        self.product_qty = move.product_uom_qty
        # action_confirm internally calls _clean_values → _set_message_step,
        # which would overwrite any custom message. So set the success
        # message AFTER action_confirm returns.
        result = self.action_confirm()
        if result:
            self._set_message(
                "success",
                self.env._("Consumed full demand: %(prod)s x%(qty)s", **{"prod": product.name, "qty": move.product_uom_qty}),
            )
        return result

    def action_consume_with_qty(self, qty):
        """Consume a specific quantity (pencil button on a move row).

        Sets the active move + qty then delegates to action_confirm.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.active_move_id:
            self._set_message("error", self.env._("No product row selected"))
            return False
        product = self.active_move_id.product_id
        if not self.location_id:
            self._set_message("error", self.env._("No source location scanned"))
            return False
        qty = float(qty) if qty else 0.0
        if qty <= 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.product_qty = qty
        result = self.action_confirm()
        if result:
            self._set_message(
                "success",
                self.env._("Consumed: %(prod)s x%(qty)s", **{"prod": product.name, "qty": qty}),
            )
        return result

    def action_add_move_quantity(self, move_id, quantity=None, package_id=None):
        """Add one unit to a non-tracked row's picked quantity.

        Available in both mandatory and optional policies — non-tracked
        products don't need a lot/serial scan, so the operator may
        always add quantity directly through this shortcut.

        A non-tracked move is displayed as one row per destination
        package plus one row for the unpacked remainder (official
        barcode behaviour), so ``package_id`` scopes the shortcut to the
        clicked row: a package id targets that package's lines, ``False``
        targets the unpacked remainder. ``None`` keeps the legacy
        whole-move behaviour.

        Without ``quantity`` one unit is added to the scoped total. An
        explicit ``quantity`` keeps the legacy SET semantics (target
        picked quantity).

        Tracked products use the per-lot +1 button inside reserved
        badges (optional policy only), handled by
        :meth:`action_pick_reserved_lot`.
        """
        self.ensure_one()
        move = self.picking_id.move_ids.filtered(
            lambda candidate: (
                candidate.id == move_id
                and candidate.state not in ("done", "cancel")
                and candidate.product_id.tracking == "none"
            )
        )
        if not move:
            self._set_message(
                "error",
                self.env._("Cannot consume tracked product by demand; scan the lot"),
            )
            return False
        if not self.set_active_move(move.id):
            return False
        if quantity is None:
            target_qty = sum(
                self._untracked_scope_lines(move, package_id).mapped("quantity")
            ) + 1.0
        else:
            target_qty = float(quantity)
        return self._set_untracked_move_qty(move, target_qty, package_id)

    def action_validate_picking(self):
        """Validate the current picking (finalize the transfer).

        Wraps picking.button_validate(). When Odoo returns a backorder
        wizard (act_window dict), the views key is patched so the OWL
        client action can open it without crashing on _preprocessAction.
        Returns True when the picking is validated directly (no wizard).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        picking = self.picking_id
        if not picking:
            self._set_message("error", self.env._("No transfer selected"))
            return False
        # Pack check: if required, all picked lines must be in a package.
        if self._lines_need_pack(picking):
            unpacked = picking.move_line_ids.filtered(
                lambda l: l.picked and not l.result_package_id
            )
            if unpacked:
                self._set_message(
                    "error",
                    self.env._("All picked products must be put into a package "
                      "before validation.")
                )
                return False
        self._normalize_zero_demand(picking)
        result = picking.button_validate()
        if isinstance(result, dict):
            # Crash-guard only: core _action_generate_backorder_wizard
            # already returns 'views': [(view.id, 'form')]. This setdefault
            # is NOT a restore of the backorder's specific view — it only
            # ensures the 'views' key exists so the client action's
            # _preprocessAction (which maps views) cannot crash on a
            # dict that somehow lacks it. view_id=False falls back to the
            # model's default form view.
            result.setdefault("views", [(False, "form")])
            return result
        # result is True (picking validated) or None/False (already done)
        return result

    def _normalize_zero_demand(self, picking):
        """Give package-only moves a demand before validating.

        Transfers created from packages carry the quantity on their move
        lines while the move demand stays 0. Core's backorder check skips
        zero-demand moves, so validating such a transfer would silently
        complete and drop every unpicked line. Mirroring the line quantity
        into the demand lets core compute the shortage and ask for the
        backorder the operation type is configured for.
        """
        self.ensure_one()
        for move in picking.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
            and not m.product_uom_qty
        ):
            quantity = sum(move.move_line_ids.mapped("quantity"))
            if quantity:
                move.product_uom_qty = quantity

    def switch_to_backorder_if_any(self):
        """After validating a picking that generated a backorder, switch
        the wizard to the newly created backorder so the operator can
        continue picking the remaining quantity.

        Called from the frontend once the backorder confirmation wizard
        has closed. Returns True if switched to a backorder, False if
        there is none (e.g. the picking was fully processed).
        """
        self.ensure_one()
        picking = self.picking_id
        if not picking or picking.state != "done":
            return False
        backorder = picking.backorder_ids[:1]
        if backorder:
            self._switch_picking(backorder)
            return True
        return False

    def action_put_in_pack(self):
        """Put all picked (and unpacked) move lines into a new package.

        Calls picking.action_put_in_pack() with the barcode_view context.

        Return value contract (forwarded to the frontend's three-state
        handler ``_handleActionResult``):
          - False: guard blocked it / no transfer / exception
          - True:  packed directly (operation type does not require a
                   package type)
          - dict:  Odoo's ``stock.put.in.pack`` wizard action — the
                   operation type requires a package type
                   (``set_package_type``). The frontend opens it; once
                   the operator picks a package type and confirms, Odoo
                   creates the package and the frontend refreshes.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        picking = self.picking_id
        if not picking:
            self._set_message("error", self.env._("No transfer selected"))
            return False
        # Fresh search to avoid stale cached picked values.
        # Use picked=True as the source of truth: scanned lines always
        # have picked=True set by _process_stock_move_line. Pre-filled
        # reception lines (quantity set, picked=False) must not be
        # packed before they are actually scanned.
        unpacked = self.env["stock.move.line"].search([
            ("picking_id", "=", picking.id),
            ("state", "not in", ("done", "cancel")),
            ("picked", "=", True),
        ]).filtered(lambda l: not l.result_package_id)
        if not unpacked:
            self._set_message(
                "info",
                self.env._("No unpacked picked products to pack."),
            )
            return True
        # Ensure picked=True so Odoo's native pack logic picks them up.
        unpacked.write({"picked": True})
        try:
            # Call action_put_in_pack directly on the filtered lines
            # instead of picking.action_put_in_pack() to avoid stale
            # picking.move_line_ids cache.
            result = unpacked.with_context(
                barcode_view=True
            ).action_put_in_pack()
        except Exception as exc:
            # Core creates the package and writes result_package_id BEFORE
            # calling _post_put_in_pack_hook (label printing). If the lines
            # are packed now, only the label step failed: report "packed,
            # printing failed" instead of a misleading pack failure.
            packed_now = self.env["stock.move.line"].search_count([
                ("id", "in", unpacked.ids),
                ("result_package_id", "!=", False),
            ])
            if packed_now:
                self._set_message(
                    "warning",
                    self.env._(
                        "装包成功、打印失败：%(msg)s", **{"msg": str(exc)}
                    ),
                )
                return True
            self._set_message(
                "error",
                self.env._("Failed to put in package: %(msg)s", **{"msg": str(exc)}),
            )
            return False
        # If Odoo returned a wizard action (package type required),
        # forward it to the frontend so the operator can choose.
        if isinstance(result, dict) and result.get("type"):
            return result
        self._set_message(
            "success",
            self.env._("Products have been put into a package."),
        )
        return True

    def action_edit_package_name(self, package_id, new_name):
        """Rename a package (used by the inline edit button)."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        new_name = (new_name or "").strip()
        if not new_name:
            self._set_message("error", self.env._("Package name cannot be empty."))
            return False
        package = self.env["stock.package"].browse(package_id)
        if not package.exists():
            self._set_message("error", self.env._("Package not found."))
            return False
        package.name = new_name
        self._set_message(
            "success",
            self.env._("Package renamed to %s.", new_name),
        )
        return True

    def action_unpack_package(self, package_id, move_id=False):
        """Remove a package from the picked lines of a specific move.

        Clears ``result_package_id`` on the picked move lines of the current
        picking that point at ``package_id`` AND belong to ``move_id``. When
        ``move_id`` is omitted, all picked lines using the package are
        cleared (legacy behaviour).

        Scoping by move ensures that removing a shared package name from one
        product does not also strip it from other products that happen to use
        the same package.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        domain = [
            ("picking_id", "=", self.picking_id.id),
            ("result_package_id", "=", package_id),
            ("state", "not in", ("done", "cancel")),
            ("picked", "=", True),
        ]
        if move_id:
            domain.append(("move_id", "=", move_id))
        lines = self.env["stock.move.line"].search(domain)
        if not lines:
            self._set_message("info", self.env._("No picked lines in this package."))
            return True
        lines.result_package_id = False
        self._set_message(
            "info",
            self.env._("Package removed; products are now unpacked."),
        )
        return True

    def action_select_existing_package(self, package_id):
        """Bind all unpacked picked lines to an existing package."""
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        package = self.env["stock.package"].browse(package_id)
        if not package.exists():
            self._set_message("error", self.env._("Package not found."))
            return False
        unpacked = self.picking_id.move_line_ids.filtered(
            lambda l: l.picked and not l.result_package_id
        )
        if not unpacked:
            self._set_message(
                "info",
                self.env._("No unpacked picked products to bind."),
            )
            return True
        unpacked.write({"picked": True})
        unpacked.result_package_id = package.id
        self._set_message(
            "success",
            self.env._("Products added to package %s.", package.name),
        )
        return True

    def action_open_package_selector(self):
        """Return an act_window action to pick an existing package.

        The frontend opens it and calls ``action_select_existing_package``
        with the chosen package id.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.package",
            "view_mode": "list,form",
            "target": "current",
            "name": self.env._("Select Package"),
        }

    def set_active_move(self, move_id):
        """Bind the operator's target move (RPC entry for row click).

        Rejects moves that do not belong to the current picking so a
        stale click cannot redirect the scan to an unrelated move.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.picking_id:
            return False
        if not move_id:
            # Clicking the selected row again clears the selection (toggle).
            self.active_move_id = False
            self._set_message_step()
            return True
        move = self.env["stock.move"].browse(move_id)
        if not move or move.picking_id != self.picking_id:
            return False
        self.active_move_id = move
        self._set_message_step()
        return True

    def _create_picking_move(self, product, quantity):
        """Create and confirm a distinct move using the scan locations."""
        self.ensure_one()
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": quantity,
            "product_uom": self.product_uom_id.id or product.uom_id.id,
            "picking_id": self.picking_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": (
                self.location_dest_id.id
                if self.location_dest_id
                else self.picking_id.location_dest_id.id
            ),
        })
        # merge=False keeps the new move distinct from existing moves for
        # the same product (otherwise _action_confirm merges them and the
        # newly-created record is unlinked, breaking active_move_id).
        move._action_confirm(merge=False)
        if self.allow_new_products:
            # Empty transfer from the workbench: drop the automatic
            # reservation of the scanned lot so the picked line created by
            # _process_stock_move_line is the only one.
            move._do_unreserve()
        # Refresh the cached move collection for the following line write.
        self.picking_id.invalidate_recordset(["move_ids"])
        return move

    def action_force_add(self, product_id=None):
        """Temporarily add a non-tracked product to the picking and
        consume the scanned quantity.

        Creates a new stock.move on the current picking (explicit fields:
        picking_id, product_id, product_uom_qty, location_id,
        location_dest_id from picking.location_dest_id), confirms it, then
        consumes via ``_process_stock_move_line``.

        Tracked products are rejected (lot/serial picking requires lot
        scanning).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return False
        if product_id:
            product = self.env["product.product"].browse(product_id)
        else:
            product = self.product_id
        if not product:
            self._set_message("error", self.env._("No product to add"))
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                self.env._("Force add only supports non-tracked products"),
            )
            return False
        if not self.location_id:
            self._set_message("error", self.env._("No source location scanned"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False
        move = self._create_picking_move(product, self.product_qty)
        added_qty = self.product_qty
        # Set product context so _process_stock_move_line finds the move
        self.product_id = product
        self.product_uom_id = self.product_uom_id or product.uom_id
        self.active_move_id = move
        move_dic = self._process_stock_move_line()
        if move_dic:
            self.visible_force_add = False
            if self.picking_id.state == "draft":
                # Empty transfer created from the workbench: confirm it now
                # that the forced move exists.
                self.picking_id.action_confirm()
            # _clean_values calls _set_message_step which overwrites
            # custom messages, so set success AFTER it. It also resets
            # product_qty, hence the captured ``added_qty``.
            self._clean_values()
            self._set_message(
                "success",
                self.env._("Added & picked: %(prod)s x%(qty)s", **{"prod": product.name, "qty": added_qty}),
            )
            return move_dic
        return False

    def action_force_add_from_barcode(self, barcode):
        """Force-add a product from an unmatched barcode.

        Frontend contract: when ``process_barcode_and_dispatch`` returns
        ``message_type == "not_found"``, the frontend offers a "Force add"
        button. The user clicks it and the frontend calls this method
        with the same barcode string. The server resolves the product by
        barcode (single source of truth — the frontend never RPCs
        product search) and delegates to ``action_force_add``.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not barcode:
            self._set_message("error", self.env._("No barcode to add"))
            return False
        product = self.env["product.product"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not product:
            self._set_message(
                "error",
                self.env._("No product found for barcode: %s", barcode),
            )
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                self.env._("Force add only supports non-tracked products"),
            )
            return False
        if not self.location_id:
            self._set_message("error", self.env._("No source location scanned"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False
        return self.action_force_add(product_id=product.id)

    # --- Correct a scanned lot / SN by exact move line ---
    def _get_picked_lot_line(self, line_id):
        """Return an editable picked line owned by the current picking.

        Every correction RPC passes through the same candidate-selector,
        transfer-state, ownership and picked-state guards. In particular,
        a line ID copied from another picking can never be used to mutate
        that other transfer.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return self.env["stock.move.line"]
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return self.env["stock.move.line"]
        if self.picking_state in ("draft", "done", "cancel"):
            self._set_message(
                "error",
                self.env._("Transfer is %(state)s, cannot scan", **{
                    "state": self.picking_state,
                }),
            )
            return self.env["stock.move.line"]
        line = self.env["stock.move.line"].search([
            ("id", "=", line_id),
            ("picking_id", "=", self.picking_id.id),
            ("state", "not in", ("done", "cancel")),
        ])
        if not line or not line.lot_id or line.product_id.tracking == "none":
            self._set_message("error", self.env._("Lot/SN not found on this move"))
            return self.env["stock.move.line"]
        if not line.picked:
            self._set_message(
                "error", self.env._("Only picked lot/SN lines can be corrected")
            )
            return self.env["stock.move.line"]
        return line

    def action_edit_move_line_qty(self, line_id, qty, force=False):
        """SET the quantity of one exact picked lot line.

        Other lines of the same lot or product are deliberately untouched.
        Demand is calculated with the same product-wide scope as scanning;
        the configured allow/warn/forbid policy also remains unchanged.
        ``force`` only bypasses a warn, never a forbid policy.
        """
        self.ensure_one()
        line = self._get_picked_lot_line(line_id)
        if not line:
            return False
        if line.product_id.tracking == "serial":
            self._set_message(
                "error", self.env._("Serial number quantity is fixed at 1")
            )
            return False
        qty = float(qty) if qty else 0.0
        if qty <= 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False

        product = line.product_id
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        total_demand = sum(m.product_uom_qty for m in moves)
        other_picked_qty = sum(
            other.quantity
            for other in moves.move_line_ids
            if other.picked and other.id != line.id
        )
        max_quantity = total_demand - other_picked_qty
        exceeds = float_compare(
            qty,
            max_quantity,
            precision_rounding=product.uom_id.rounding,
        ) > 0
        policy = self._get_excess_qty_policy()
        if exceeds and policy == "forbid":
            self._set_message(
                "error",
                self.env._(
                    "Quantity exceeds demand (max: %(max)s). "
                    "Over-picking is forbidden for this operation type.",
                    max=max_quantity,
                ),
            )
            return False
        if exceeds and policy == "warn" and not force:
            self._set_message(
                "more_match",
                self.env._("Quantity exceeds demand (max: %s)", max_quantity),
            )
            return False

        line.quantity = qty
        self._set_message(
            "success",
            self.env._(
                "Updated lot/SN quantity: %(lot)s x%(qty)s",
                lot=line.lot_id.name,
                qty=qty,
            ),
        )
        return True

    def _untracked_scope_lines(self, move, package_id=None):
        """Return the unscoped picked lines of a non-tracked row.

        ``package_id=None`` keeps the legacy whole-move scope. A package
        id targets the lines packed into that package, ``False`` targets
        the unpacked remainder row (official barcode row split).
        """
        picked_lines = move.move_line_ids.filtered("picked")
        if package_id is None:
            return picked_lines
        return picked_lines.filtered(
            lambda line: (line.result_package_id.id or False) == package_id
        )

    def _set_untracked_move_qty(self, move, qty, package_id=None, force=False):
        """SET the total picked quantity of one non-tracked row.

        The quantity rows of the scan view show one aggregate "picked"
        figure each (whole move, one destination package, or the
        unpacked remainder), so both the pencil editor and the ``+1``
        shortcut work on that row total. The difference between the
        requested value and the current total is applied to the scoped
        picked lines instead of replacing only the first line —
        otherwise editing an aggregated row silently lost the quantity
        held by the other lines/packages.

        Entering 0 clears the scoped picked lines (``quantity = 0`` with
        ``picked = False``) but keeps them, so the product row stays
        visible in the scan view.
        """
        self.ensure_one()
        qty = float(qty) if qty else 0.0
        if qty < 0:
            self._set_message("error", self.env._("Quantity must be positive"))
            return False
        product = move.product_id
        rounding = product.uom_id.rounding
        picked_lines = self._untracked_scope_lines(
            move, package_id
        ).sorted(lambda line: line.id)
        if not picked_lines:
            if qty <= 0:
                return True
            if package_id:
                # A package row always has picked lines; an empty list
                # here means the row is stale (e.g. the package was
                # removed meanwhile).
                self._set_message(
                    "error", self.env._("Package line not found")
                )
                return False
            # Unpacked remainder row: let the regular consume flow create
            # the line (it also honours the source/destination locations
            # and the current package intent). The consume flow works on
            # the active move, which may be another row when the editor
            # is opened directly.
            if not self.set_active_move(move.id):
                return False
            return bool(self.action_consume_with_qty(qty))
        scope_ids = set(picked_lines.ids)
        moves = self.picking_id.move_ids.filtered(
            lambda candidate: (
                candidate.product_id == product
                and candidate.state != "cancel"
            )
        )
        total_demand = sum(candidate.product_uom_qty for candidate in moves)
        other_picked_qty = sum(
            line.quantity
            for line in moves.move_line_ids
            if line.picked and line.id not in scope_ids
        )
        max_quantity = total_demand - other_picked_qty
        if float_compare(qty, max_quantity, precision_rounding=rounding) > 0:
            policy = self._get_excess_qty_policy()
            if policy == "forbid":
                self._set_message(
                    "error",
                    self.env._(
                        "Quantity exceeds demand (max: %(max)s). "
                        "Over-picking is forbidden for this operation type.",
                        max=max_quantity,
                    ),
                )
                return False
            if policy == "warn" and not force:
                # Remember the blocked target so the footer force button
                # can apply it once the operator confirms. 'forbid' above
                # is never bypassed, even with force.
                self.pending_add = {
                    "move_id": move.id,
                    "qty": qty,
                    "package_id": package_id or False,
                }
                self.visible_force_done = True
                self._set_message(
                    "more_match",
                    self.env._(
                        "Quantity exceeds demand (max: %s). Confirm to force.",
                        max_quantity,
                    ),
                )
                return False
        delta = qty - sum(picked_lines.mapped("quantity"))
        if delta > 0:
            last_line = picked_lines[-1]
            last_line.quantity = last_line.quantity + delta
        elif delta < 0:
            remaining = -delta
            for line in reversed(picked_lines):
                take = min(line.quantity, remaining)
                line.quantity = line.quantity - take
                remaining -= take
                if float_is_zero(line.quantity, precision_rounding=rounding):
                    line.quantity = 0.0
                    line.picked = False
                if remaining <= 0:
                    break
        self._set_message(
            "success",
            self.env._("Consumed: %(prod)s x%(qty)s", prod=product.name, qty=qty),
        )
        return True

    def action_edit_move_line(
        self,
        line_id,
        qty=None,
        lot_name=None,
        package_name=None,
        result_package_name=None,
    ):
        """Row editor: change quantity, lot/serial and packages of a line.

        Only lines of the current transfer can be edited. Quantity goes
        through the standalone quantity editor so the excess policy stays
        in force; lot and package names are resolved (or created when the
        operation type allows it) before writing.

        Non-tracked products have no lot: their quantity rows are split
        per destination package (plus the unpacked remainder), so the
        requested value and the package names are applied to the lines
        of the clicked row only.
        """
        self.ensure_one()
        line = self.env["stock.move.line"].browse(line_id)
        if (
            not line.exists()
            or line.picking_id != self.picking_id
            or line.state in ("done", "cancel")
        ):
            self._set_message("error", self.env._("Line not found."))
            return False
        # Row scope of a non-tracked move (package id, or False for the
        # unpacked remainder). Computed before the quantity edit, which
        # may unpick some of the scoped lines.
        row_package_id = line.result_package_id.id or False
        package_targets = line
        if line.product_id.tracking == "none":
            scoped_lines = self._untracked_scope_lines(
                line.move_id, row_package_id
            )
            if scoped_lines:
                package_targets = scoped_lines
        if qty is not None:
            if line.product_id.tracking == "none":
                handled = self._set_untracked_move_qty(
                    line.move_id, qty, row_package_id
                )
            else:
                handled = self.action_edit_move_line_qty(line.id, qty)
            if not handled:
                return False
            line = self.env["stock.move.line"].browse(line_id)
        if lot_name is not None:
            current = line.lot_id.name or line.lot_name or ""
            if lot_name and lot_name != current:
                lot = self.env["stock.lot"].search([
                    ("name", "=", lot_name),
                    ("product_id", "=", line.product_id.id),
                ], limit=1)
                if lot:
                    line.write({"lot_id": lot.id, "lot_name": lot.name})
                elif self.picking_id.picking_type_id.use_create_lots:
                    lot = self.env["stock.lot"].create({
                        "name": lot_name,
                        "product_id": line.product_id.id,
                        "company_id": line.company_id.id,
                    })
                    line.write({"lot_id": lot.id, "lot_name": lot.name})
                else:
                    self._set_message(
                        "error",
                        self.env._(
                            "This operation type does not allow creating new lots.",
                        ),
                    )
                    return False
        # Package names typed in the row editor apply to the lines of the
        # clicked row only (that package's lines, or the unpacked
        # remainder) — see package_targets above.
        for field_name, package_value in (
            ("package_id", package_name),
            ("result_package_id", result_package_name),
        ):
            if package_value is None:
                continue
            if not package_value:
                package_targets.write({field_name: False})
                continue
            package = self.env["stock.package"].search([
                ("name", "=", package_value),
            ], limit=1)
            if not package:
                package = self.env["stock.package"].create(
                    {"name": package_value}
                )
            package_targets.write({field_name: package.id})
        self._set_message("success", self.env._("Line updated."))
        return True

    def action_edit_package_qty(self, move_id, package_id, qty, force=False):
        """SET the picked quantity of one move's lines inside one package.

        The card-head quantity editor of a packaged row must change the
        packed lines themselves. The regular consume flow
        (``action_consume_with_qty``) only targets *unpacked* lines, so
        editing a packaged row used to leave it untouched.

        Demand is checked with the same product-wide scope and over-picking
        policy as scanning; ``force`` only bypasses a warn, never a forbid.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.picking_id:
            self._set_message("error", self.env._("No transfer selected"))
            return False
        if self.picking_state in ("draft", "done", "cancel"):
            self._set_message(
                "error",
                self.env._("Transfer is %(state)s, cannot scan", **{
                    "state": self.picking_state,
                }),
            )
            return False
        move = self.picking_id.move_ids.filtered(
            lambda m: m.id == move_id and m.state not in ("done", "cancel")
        )
        lines = move.move_line_ids.filtered(
            lambda l: l.picked and l.result_package_id.id == package_id
        ).sorted(key=lambda l: l.id)
        if not lines:
            self._set_message("error", self.env._("Package line not found"))
            return False
        if lines[0].product_id.tracking == "serial":
            self._set_message(
                "error", self.env._("Serial number quantity is fixed at 1")
            )
            return False
        qty = float(qty) if qty else 0.0
        if qty <= 0:
            # The design keeps a single edit button per product (no trash):
            # entering 0 clears the package row instead of deleting it.
            lines.write({"quantity": 0.0, "picked": False})
            self._set_message(
                "success",
                self.env._("Cleared the picked quantity of the package."),
            )
            return True
        product = lines[0].product_id
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        total_demand = sum(m.product_uom_qty for m in moves)
        other_picked_qty = sum(
            other.quantity
            for other in moves.move_line_ids
            if other.picked and other.id not in lines.ids
        )
        max_quantity = total_demand - other_picked_qty
        exceeds = float_compare(
            qty,
            max_quantity,
            precision_rounding=product.uom_id.rounding,
        ) > 0
        policy = self._get_excess_qty_policy()
        if exceeds and policy == "forbid":
            self._set_message(
                "error",
                self.env._(
                    "Quantity exceeds demand (max: %(max)s). "
                    "Over-picking is forbidden for this operation type.",
                    max=max_quantity,
                ),
            )
            return False
        if exceeds and policy == "warn" and not force:
            self._set_message(
                "more_match",
                self.env._("Quantity exceeds demand (max: %s)", max_quantity),
            )
            return False
        # One package row aggregates its lines: put the new total on the
        # first line and drop the now redundant ones.
        first = lines[0]
        first.quantity = qty
        for extra in lines[1:]:
            extra.unlink()
        self._set_message(
            "success",
            self.env._(
                "Updated package quantity: %(pkg)s x%(qty)s",
                pkg=first.result_package_id.name,
                qty=qty,
            ),
        )
        return True

    def action_remove_move_lot(self, line_id):
        """Remove one unit from an exact picked lot/SN move line.

        Ordinary lot lines keep their existing behaviour: quantity > 1 is
        decremented by one; quantity 1 and serial lines are unlinked. The
        ``stock.lot`` inventory record itself is never deleted.
        """
        self.ensure_one()
        line = self._get_picked_lot_line(line_id)
        if not line:
            return False
        if line.quantity > 1:
            line.quantity -= 1
            if line.quantity <= 0:
                line.unlink()
        else:
            line.unlink()
        self._set_message(
            "success",
            self.env._("Removed lot/SN from the transfer.")
        )
        return True

    def action_remove_move_qty(self, row_key):
        """Clear the picked quantity of one product/package row.

        Quantity-tracked counterpart of ``action_remove_move_lot``: the
        trash button of a row only resets the picked quantity to 0. The
        move lines are kept on purpose, so the product row stays visible
        in the scan view instead of disappearing from the move list.
        """
        self.ensure_one()
        # row_key format: "{move_id}_{pkg_id|nopkg}_{location_id|0}"
        parts = (row_key or "").split("_")
        if len(parts) < 3 or not parts[0].isdigit():
            return False
        move_key = parts[0]
        pkg_key = parts[1]
        loc_key = parts[2]
        pkg_id = False if pkg_key in ("", "nopkg") else int(pkg_key)
        loc_id = False if loc_key in ("", "0") else int(loc_key)
        mv = self.picking_id.move_ids.filtered(lambda m: m.id == int(move_key))
        lines = mv.move_line_ids.filtered(
            lambda l: l.picked
            and (l.result_package_id.id or False) == pkg_id
            and (l.location_id.id or False) == loc_id
        )
        if not lines:
            return False
        lines.write({"quantity": 0.0, "picked": False})
        self._set_message(
            "success",
            self.env._("Removed the picked quantity of the row.")
        )
        return True

    def _get_picking_action_menu_items(self):
        """Return the picking form's toolbar items (actions + print).

        These are the exact same items shown in the native Odoo cog menu
        on the stock.picking form view — Unreserve / Lock / Scrap / ...
        plus the print reports. The frontend renders them via the standard
        ``web.CogMenu`` OWL component, so the UI looks 100% native.
        """
        self.ensure_one()
        if not self.picking_id:
            return {"action": [], "print": []}
        picking_model = self.env["stock.picking"]
        # Pick the canonical form view (user may have custom views; the
        # stock module ships the primary one which carries the toolbar).
        view_id = self.env.ref("stock.view_picking_form").id
        try:
            result = picking_model.get_views(
                [(view_id, "form")], {"toolbar": True}
            )
            toolbar = result["views"]["form"].get("toolbar", {})
        except Exception:
            toolbar = {}
        return {
            "action": toolbar.get("action", []),
            "print": toolbar.get("print", []),
        }

    def action_add_product_to_picking(self, product_id, qty=1.0):
        """Add a product to the current picking and create a stock.move.

        Called from the scan UI's "Add Product" button when the operator
        wants to pick a product that isn't on the transfer yet (force-add).
        """
        _log = self.env['ir.logging']._log if hasattr(self.env['ir.logging'], '_log') else None
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        _logger.warning("=== action_add_product_to_picking CALLED: wiz=%s picking=%s product_id=%s qty=%s ===",
                        self.id, self.picking_id.name, product_id, qty)
        self.ensure_one()
        if not self.picking_id:
            _logger.warning("action_add_product_to_picking: NO picking_id!")
            return False
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            _logger.warning("action_add_product_to_picking: product %s not found!", product_id)
            return False
        # If the product is already on the picking, increase the demand of
        # the first open move instead of refusing — the operator may need to
        # pick more of the same product (e.g. already-picked qty is packed
        # but extra units just arrived).
        existing = self.picking_id.move_ids.filtered(
            lambda m: m.product_id.id == product_id and m.state not in ("done", "cancel")
        )
        if existing:
            move = existing[0]
            # 已拣量可能超过需求（超拣/历史数据），必须在 max(需求, 已拣)
            # 的基础上加，否则 demand-qty 为负，未装包剩余行永远不会出现。
            move.product_uom_qty = max(move.product_uom_qty, move.quantity) + qty
            self._set_message(
                "success",
                self.env._("Product already on the transfer — demand increased by %s.") % qty
            )
            return True
        src_loc = self.location_id or self.picking_location_id
        dst_loc = self.location_dest_id or self.picking_location_dest_id
        self.picking_id.move_ids.create({
            "product_id": product_id,
            "product_uom": product.uom_id.id,
            "product_uom_qty": qty,
            "location_id": src_loc.id,
            "location_dest_id": dst_loc.id,
            "picking_id": self.picking_id.id,
            "state": "confirmed",
        })
        self._set_message(
            "success",
            self.env._("Product added to the transfer — scan to pick.")
        )
        return True

    # --- Cleanup ---
    def _clean_values(self):
        """Clean scanned values after successful confirmation.

        product_id is cleared, which cascades to product_tracking
        (related field) and re-enables the lot step in the UI.

        active_move_id is intentionally preserved: the operator keeps
        scanning serial numbers/lots of the same product in a row, and
        re-clicking the product row after each scan would be wasteful on
        a shop-floor device. It is switched or cleared explicitly when
        another product is scanned (_scan_product / _resolve_lot_owner)
        or when the move is fully picked (see _create_new_lot_flow).
        """
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.visible_force_done = False
        self.visible_force_add = False
        self.pending_add = False
        self.step = self._step_index("product")
        self._set_message_step()
