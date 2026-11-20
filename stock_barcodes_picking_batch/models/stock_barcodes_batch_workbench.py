# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

BATCH_ACTIVE_STATES = ("draft", "in_progress")
BATCH_LIST_STATES = ("draft", "in_progress", "done")
BATCH_PICKING_STATES = ("draft", "confirmed", "waiting", "assigned")


class StockBarcodesWorkbench(models.Model):
    _inherit = "stock.barcodes.workbench"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_batches(self, warehouse, states=None):
        types = self._get_workbench_types(warehouse)
        if not types:
            return self.env["stock.picking.batch"]
        domain = [("picking_type_id", "in", types.ids)]
        if states:
            domain.append(("state", "in", list(states)))
        return self.env["stock.picking.batch"].search(
            domain, order="state, scheduled_date desc, id desc"
        )

    def _batch_date_label(self, batch):
        moment = batch.scheduled_date or batch.create_date
        if not moment:
            return ""
        local = fields.Datetime.context_timestamp(batch, moment)
        return f"{local.month}月{local.day}日"

    def _batch_datetime_label(self, batch):
        moment = batch.scheduled_date or batch.create_date
        if not moment:
            return ""
        local = fields.Datetime.context_timestamp(batch, moment)
        return (
            f"{local.year}年{local.month}月{local.day}日 "
            f"{local.hour:02d}时{local.minute:02d}分{local.second:02d}秒"
        )

    def _serialize_batch(self, batch):
        pickings = batch.picking_ids
        done = len(pickings.filtered(lambda picking: picking.state == "done"))
        picking = pickings[:1]
        return {
            "id": batch.id,
            "name": batch.name,
            "state": batch.state,
            "state_label": dict(
                batch._fields["state"].selection
            ).get(batch.state, batch.state),
            "total": len(pickings),
            "done": done,
            "detail_count": len(batch.move_line_ids),
            "warehouse": (
                batch.picking_type_id.warehouse_id.name
                or batch.picking_type_id.warehouse_id.code
                or ""
            ),
            "operation_type": batch.picking_type_id.name or "",
            "partner": (picking.partner_id.name if picking else "") or "",
            "responsible": batch.user_id.name or batch.create_uid.name or "",
            "date": self._batch_date_label(batch),
            "datetime_label": self._batch_datetime_label(batch),
        }

    def _batch_domain(self, warehouse):
        types = self._get_workbench_types(warehouse)
        if not types:
            return [("id", "=", 0)]
        return [("picking_type_id", "in", types.ids)]

    def _batch_candidate_domain(self, picking_type):
        return [
            ("picking_type_id", "=", picking_type.id),
            ("state", "in", BATCH_PICKING_STATES),
            ("batch_id", "=", False),
        ]

    # ------------------------------------------------------------------
    # workbench card
    # ------------------------------------------------------------------

    @api.model
    def get_workbench_data(self, warehouse_id=None):
        data = super().get_workbench_data(warehouse_id)
        warehouse = self._get_warehouse(warehouse_id)
        active_batches = self._get_batches(warehouse, BATCH_ACTIVE_STATES)
        data["batch_enabled"] = True
        data["types"].append(
            {
                "id": False,
                "key": "batch",
                "name": "批量调拨",
                "display_name": "批量调拨",
                "subtitle": "BATCH TRANSFERS",
                "code": "BATCH",
                "color": "batch",
                "count": len(active_batches),
                "virtual": True,
                "action": "stock_barcodes_picking_batch.action_batch_workbench",
            }
        )
        return data

    # ------------------------------------------------------------------
    # batch list
    # ------------------------------------------------------------------

    @api.model
    def get_batch_list(
        self, warehouse_id=None, state_filter="all", page=1, page_size=80
    ):
        warehouse = self._get_warehouse(warehouse_id)
        base = self._batch_domain(warehouse)
        page = max(1, int(page or 1))
        page_size = min(200, max(1, int(page_size or 80)))
        Batch = self.env["stock.picking.batch"]

        facets = []
        for key, label, color, stat_color in (
            ("all", "所有", "all", "all"),
            ("draft", "草稿", "draft", "gray"),
            ("in_progress", "进行中", "ongoing", "yellow"),
            ("done", "已完成", "done_today", "green"),
        ):
            domain = (
                base + [("state", "in", BATCH_LIST_STATES)]
                if key == "all"
                else base + [("state", "=", key)]
            )
            facets.append(
                {
                    "key": key,
                    "label": label,
                    "color": color,
                    "stat_color": stat_color,
                    "count": Batch.search_count(domain),
                }
            )

        domain = base + [("state", "in", BATCH_LIST_STATES)]
        if state_filter and state_filter != "all":
            if state_filter not in BATCH_LIST_STATES:
                raise UserError(_("Invalid batch state filter."))
            domain = base + [("state", "=", state_filter)]
        total = Batch.search_count(domain)
        batches = Batch.search(
            domain,
            order="state, scheduled_date desc, id desc",
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "records": [self._serialize_batch(batch) for batch in batches],
            "facets": facets,
        }

    @api.model
    def get_batch_info(self, batch_id):
        """Small header payload used by the add-pickings page."""
        batch = self.env["stock.picking.batch"].browse(int(batch_id)).exists()
        if not batch:
            raise UserError(_("The batch transfer no longer exists."))
        pickings = batch.picking_ids
        return {
            "id": batch.id,
            "name": batch.name,
            "state": batch.state,
            "total": len(pickings),
            "done": len(pickings.filtered(lambda p: p.state == "done")),
            "can_add": batch.state in BATCH_ACTIVE_STATES,
            "warehouse": batch.picking_type_id.warehouse_id.name or "",
        }

    # ------------------------------------------------------------------
    # create batch (operation type first)
    # ------------------------------------------------------------------

    @api.model
    def get_batch_create_types(self, warehouse_id=None):
        warehouse = self._get_warehouse(warehouse_id)
        types = self._get_workbench_types(warehouse)
        result = []
        for picking_type in types:
            count = self.env["stock.picking"].search_count(
                self._batch_candidate_domain(picking_type)
            )
            payload = self._type_payload(picking_type, count)
            result.append(payload)
        return result

    @api.model
    def get_batch_candidates(self, warehouse_id=None, picking_type_id=None):
        picking_type = self.env["stock.picking.type"].browse(
            int(picking_type_id or 0)
        ).exists()
        if not picking_type:
            return []
        warehouse = self._get_warehouse(warehouse_id)
        if picking_type not in self._get_workbench_types(warehouse):
            return []
        pickings = self.env["stock.picking"].search(
            self._batch_candidate_domain(picking_type),
            order="priority desc, scheduled_date asc, id desc",
            limit=200,
        )
        return [self._serialize_picking(picking) for picking in pickings]

    @api.model
    def create_batch(self, warehouse_id, picking_type_id, picking_ids):
        warehouse = self._get_warehouse(warehouse_id)
        picking_type = self.env["stock.picking.type"].browse(
            int(picking_type_id or 0)
        ).exists()
        if not picking_type or picking_type not in self._get_workbench_types(
            warehouse
        ):
            raise UserError(_("Select an operation type first."))
        ids = [int(picking_id) for picking_id in (picking_ids or [])]
        if not ids:
            raise UserError(_("Select at least one transfer."))
        pickings = self.env["stock.picking"].search(
            [
                ("id", "in", ids),
                ("picking_type_id", "=", picking_type.id),
                ("batch_id", "=", False),
                ("state", "in", BATCH_PICKING_STATES),
            ]
        )
        if len(pickings) != len(ids):
            raise UserError(
                _("Some selected transfers are no longer available.")
            )
        batch = self.env["stock.picking.batch"].create(
            {
                "picking_type_id": picking_type.id,
                "company_id": pickings.company_id.id,
            }
        )
        pickings.write({"batch_id": batch.id})
        batch.action_confirm()
        return {
            "id": batch.id,
            "name": batch.name,
            "action": self.get_batch_scan_action(batch.id),
        }

    # ------------------------------------------------------------------
    # scan page
    # ------------------------------------------------------------------

    @api.model
    def get_batch_scan_action(self, batch_id):
        """Open the batch scan page on the first incomplete picking."""
        batch = self.env["stock.picking.batch"].browse(int(batch_id)).exists()
        if not batch:
            raise UserError(_("The batch transfer no longer exists."))
        if batch.state in ("done", "cancel"):
            return {
                "type": "ir.actions.act_window",
                "name": batch.name,
                "res_model": "stock.picking.batch",
                "res_id": batch.id,
                "views": [[False, "form"]],
                "target": "current",
            }
        if batch.state == "draft":
            batch.action_confirm()
        pickings = batch.picking_ids.filtered(
            lambda picking: picking.state not in ("done", "cancel")
        )
        ordered = pickings.sorted(
            lambda picking: (picking.scheduled_date or datetime.max, picking.id)
        )
        target = self.env["stock.picking"]
        for picking in ordered:
            for move in picking.move_ids.filtered(
                lambda move: move.state not in ("done", "cancel")
            ):
                demand = move.product_uom_qty
                if not demand:
                    demand = sum(move.move_line_ids.mapped("quantity"))
                done = sum(
                    line.quantity
                    for line in move.move_line_ids
                    if line.picked
                )
                if (
                    float_compare(
                        done,
                        demand,
                        precision_rounding=move.product_uom.rounding,
                    )
                    < 0
                ):
                    target = picking
                    break
            if target:
                break
        if not target:
            target = ordered[:1]
        if not target:
            raise UserError(_("This batch has no transfer left to pick."))
        wizard = self.env["wiz.stock.barcodes.picking"].create(
            {
                "batch_id": batch.id,
                "picking_id": target.id,
            }
        )
        wizard._set_default_values()
        self.mark_recent(target.id)
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_picking.action_picking_barcode_scan"
        )
        action["params"] = {"wiz_id": wizard.id}
        action["views"] = [(False, "list"), (False, "form")]
        return action

    # ------------------------------------------------------------------
    # add pickings to an existing batch
    # ------------------------------------------------------------------

    @api.model
    def _get_active_batch(self, batch_id):
        batch = self.env["stock.picking.batch"].browse(int(batch_id)).exists()
        if not batch:
            raise UserError(_("The batch transfer no longer exists."))
        if batch.state not in BATCH_ACTIVE_STATES:
            raise UserError(
                _("Only draft or in-progress batches can be changed.")
            )
        return batch

    @api.model
    def get_add_candidates(self, batch_id):
        batch = self._get_active_batch(batch_id)
        pickings = self.env["stock.picking"].search(
            self._batch_candidate_domain(batch.picking_type_id),
            order="priority desc, scheduled_date asc, id desc",
            limit=200,
        )
        return [self._serialize_picking(picking) for picking in pickings]

    @api.model
    def add_pickings_to_batch(self, batch_id, picking_ids):
        batch = self._get_active_batch(batch_id)
        ids = [int(picking_id) for picking_id in (picking_ids or [])]
        if not ids:
            raise UserError(_("Select at least one transfer."))
        pickings = self.env["stock.picking"].search(
            [
                ("id", "in", ids),
                ("picking_type_id", "=", batch.picking_type_id.id),
                ("batch_id", "=", False),
                ("state", "in", BATCH_PICKING_STATES),
            ]
        )
        if len(pickings) != len(ids):
            raise UserError(
                _("Some selected transfers are no longer available.")
            )
        if batch.state == "in_progress":
            pickings.filtered(
                lambda picking: picking.state == "draft"
            ).action_confirm()
        pickings.write({"batch_id": batch.id})
        return self.get_batch_info(batch.id)

    # ------------------------------------------------------------------
    # print
    # ------------------------------------------------------------------

    @api.model
    def get_batch_print_action(self, batch_id):
        batch = self.env["stock.picking.batch"].browse(int(batch_id)).exists()
        if not batch:
            raise UserError(_("The batch transfer no longer exists."))
        return batch.action_print()

    # ------------------------------------------------------------------
    # barcode
    # ------------------------------------------------------------------

    @api.model
    def scan_batch_barcode(self, barcode, warehouse_id=None):
        barcode = (barcode or "").strip()
        if not barcode:
            return {"action": "error", "message": "请先扫描条码。"}
        warehouse = self._get_warehouse(warehouse_id)
        batches = self._get_batches(warehouse, BATCH_ACTIVE_STATES).filtered(
            lambda batch: batch.name == barcode
        )
        if not batches:
            batches = self._get_batches(
                warehouse, BATCH_ACTIVE_STATES
            ).filtered(lambda batch: barcode.lower() in batch.name.lower())
        if not batches:
            return {"action": "error", "message": "未找到进行中的批量调拨。"}
        if len(batches) > 1:
            return {
                "action": "choose",
                "candidates": [
                    self._serialize_batch(batch) for batch in batches[:20]
                ],
            }
        return {
            "action": "open_batch",
            "batch_id": batches.id,
            "batch_name": batches.name,
        }
