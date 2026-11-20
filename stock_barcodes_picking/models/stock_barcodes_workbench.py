# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

# Status keys used by the workbench UI. Only the six native stock.picking
# states exist in the database; "done_today", "overdue" and "ongoing" are
# derived filters on top of them (see TO-DO LIST.md §8.3.2).
STATUS_ORDER = [
    "all",
    "draft",
    "confirmed",
    "waiting_other",
    "ready",
    "done_today",
    "overdue",
    "cancel",
    "ongoing",
]

STATUS_LABELS = {
    "all": "所有",
    "draft": "草稿",
    "confirmed": "等待",
    "waiting_other": "等待其他作业",
    "ready": "就绪",
    "done_today": "今日已完成",
    "overdue": "逾期",
    "cancel": "已取消",
    "ongoing": "进行中",
}

STATUS_COLORS = {
    "all": "all",
    "draft": "draft",
    "confirmed": "confirmed",
    "waiting_other": "waiting_other",
    "ready": "ready",
    "done_today": "done_today",
    "overdue": "overdue",
    "cancel": "cancel",
    "ongoing": "ongoing",
}

# Workbench status cards use a different palette (blue/green/pink/red/...).
STAT_COLORS = {
    "all": "all",
    "ready": "blue",
    "done_today": "green",
    "overdue": "pink",
    "cancel": "red",
    "draft": "gray",
    "confirmed": "orange",
    "waiting_other": "orange",
    "ongoing": "yellow",
}

TYPE_SEQUENCE_META = {
    "OUT": ("交货单", "OUTBOUND", "out"),
    "PC": ("拣取组件", "PICK COMPONENTS", "pc"),
    "IN": ("收据", "RECEIPTS", "in"),
    "SFP": ("存储成品", "STORE FINISHED", "sfp"),
    "INT": ("内部调拨", "INTERNAL", "int"),
    "IA": ("库存调整", "INVENTORY", "ia"),
}

MAX_RECENT = 30


class StockBarcodesWorkbench(models.Model):
    """Stateless service model for the scan workbench.

    ``_auto = False`` keeps this model table-less: uninstalling the module
    only removes its ``ir.model`` metadata, no data is left behind.
    """

    _name = "stock.barcodes.workbench"
    _description = "Barcode Scan Workbench Service"
    _auto = False
    _log_access = False

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @api.model
    def _get_warehouses(self):
        return self.env["stock.warehouse"].search(
            [("company_id", "in", self.env.companies.ids)], order="sequence, id"
        )

    @api.model
    def _get_warehouse(self, warehouse_id=None):
        warehouses = self._get_warehouses()
        if warehouse_id:
            warehouse = warehouses.filtered(lambda wh: wh.id == int(warehouse_id))
            if warehouse:
                return warehouse
        preferred = self.env.user.barcode_workbench_warehouse_id
        if preferred and preferred in warehouses:
            return preferred
        return warehouses[:1]

    @api.model
    def _get_workbench_types(self, warehouse):
        if not warehouse:
            return self.env["stock.picking.type"]
        all_types = self.env["stock.picking.type"].search(
            [("warehouse_id", "=", warehouse.id), ("active", "=", True)]
        )
        known_codes = tuple(TYPE_SEQUENCE_META)
        known = all_types.filtered(
            lambda picking_type: (picking_type.sequence_code or "").upper()
            in known_codes
        )
        types = known or all_types
        order = {code: index for index, code in enumerate(("OUT", "PC", "IN", "SFP", "INT", "IA"))}
        types = types.sorted(
            key=lambda picking_type: (
                order.get((picking_type.sequence_code or "").upper(), 99),
                picking_type.sequence,
                picking_type.id,
            )
        )
        favorite = types.filtered(
            lambda picking_type: self.env.user in picking_type.favorite_user_ids
        )
        return favorite or types

    @api.model
    def _inventory_pending_count(self, warehouse):
        if not warehouse:
            return 0
        locations = self.env["stock.location"].search(
            [("warehouse_id", "=", warehouse.id), ("usage", "=", "internal")]
        )
        if not locations:
            return 0
        return self.env["stock.quant"].search_count(
            [
                ("location_id", "in", locations.ids),
                ("inventory_date", "<=", fields.Date.today()),
            ]
        )

    @api.model
    def _today_bounds(self):
        tz_name = self.env.user.tz or "UTC"
        tz = pytz.timezone(tz_name)
        today = datetime.now(tz).date()
        start = (
            tz.localize(datetime.combine(today, time.min))
            .astimezone(pytz.utc)
            .replace(tzinfo=None)
        )
        end = (
            tz.localize(datetime.combine(today, time.max))
            .astimezone(pytz.utc)
            .replace(tzinfo=None)
        )
        return start, end

    @api.model
    def _status_domain(self, key, base=None):
        if key not in STATUS_ORDER:
            raise UserError(_("Unknown status filter: %s", key))
        base = base or []
        if key == "all":
            start, end = self._today_bounds()
            domain = Domain.OR(
                [
                    [
                        ("state", "=", "done"),
                        ("date_done", ">=", start),
                        ("date_done", "<=", end),
                    ],
                    [("state", "=", "cancel")],
                    [("state", "in", ("draft", "confirmed", "waiting", "assigned"))],
                ]
            )
            return Domain.AND([base, domain])
        if key == "done_today":
            start, end = self._today_bounds()
            return Domain.AND(
                [
                    base,
                    [
                        ("state", "=", "done"),
                        ("date_done", ">=", start),
                        ("date_done", "<=", end),
                    ],
                ]
            )
        if key == "overdue":
            now = fields.Datetime.now()
            late = [
                ("state", "in", ("assigned", "waiting", "confirmed")),
                "|",
                "|",
                ("has_deadline_issue", "=", True),
                ("date_deadline", "<", now),
                ("scheduled_date", "<", now),
            ]
            return Domain.AND([base, late])
        if key == "ongoing":
            return Domain.AND(
                [
                    base,
                    [
                        ("state", "=", "assigned"),
                        ("move_line_ids.quantity", ">", 0),
                    ],
                ]
            )
        state_by_key = {
            "draft": "draft",
            "confirmed": "confirmed",
            "ready": "assigned",
            "waiting_other": "waiting",
            "cancel": "cancel",
        }
        if key in state_by_key:
            return Domain.AND([base, [("state", "=", state_by_key[key])]])
        raise UserError(_("Unknown status filter: %s", key))

    @api.model
    def _count(self, domain):
        return self.env["stock.picking"].search_count(domain)

    @api.model
    def _counts_by_type(self, domain):
        groups = self.env["stock.picking"]._read_group(
            domain, ["picking_type_id"], ["__count"]
        )
        return {picking_type.id: count for picking_type, count in groups}

    @api.model
    def _type_meta(self, picking_type):
        sequence_code = (picking_type.sequence_code or "").upper()
        if sequence_code in TYPE_SEQUENCE_META:
            return TYPE_SEQUENCE_META[sequence_code]
        fallback = {
            "incoming": ("收据", "RECEIPTS", "in"),
            "outgoing": ("交货单", "OUTBOUND", "out"),
            "internal": ("内部调拨", "INTERNAL", "int"),
        }
        return fallback.get(
            picking_type.code,
            (picking_type.name, sequence_code or picking_type.code or "", "int"),
        )

    @api.model
    def _type_subtitle_cn(self, picking_type):
        sequence_code = (picking_type.sequence_code or "").upper()
        mapping = {
            "OUT": "发货",
            "PC": "拣配",
            "IN": "收货",
            "SFP": "成品入库",
            "INT": "内调",
            "IA": "盘点",
        }
        if sequence_code in mapping:
            return mapping[sequence_code]
        fallback = {"incoming": "收货", "outgoing": "发货", "internal": "内调"}
        return fallback.get(picking_type.code, picking_type.name)

    @api.model
    def _type_payload(self, picking_type, count=0):
        title, subtitle, color = self._type_meta(picking_type)
        return {
            "id": picking_type.id,
            "key": str(picking_type.id),
            "name": title,
            "display_name": picking_type.name,
            "subtitle": subtitle,
            "color": color,
            "count": count,
        }

    @api.model
    def _picking_status_key(self, picking):
        mapping = {
            "draft": "draft",
            "confirmed": "confirmed",
            "waiting": "waiting_other",
            "assigned": "ready",
            "done": "done_today",
            "cancel": "cancel",
        }
        return mapping.get(picking.state, "draft")

    @api.model
    def _serialize_picking(self, picking):
        moment = picking.date_done if picking.state == "done" else picking.scheduled_date
        moment = moment or picking.create_date
        date_label = ""
        if moment:
            local = fields.Datetime.context_timestamp(picking, moment)
            date_label = f"{local.month}月{local.day}日"
        partner = (
            picking.partner_id.name
            or picking.location_dest_id.display_name
            or picking.location_id.display_name
            or ""
        )
        return {
            "id": picking.id,
            "name": picking.name,
            "state": picking.state,
            "status_key": self._picking_status_key(picking),
            "origin": picking.origin or "",
            "partner": partner,
            "date": date_label,
            "starred": picking.priority == "1",
        }

    @api.model
    def _recent_pickings(self):
        recent = self.env["stock.barcodes.picking.recent"].search(
            [("user_id", "=", self.env.user.id)],
            order="last_seen desc, id desc",
            limit=MAX_RECENT,
        )
        return recent.picking_id.exists()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @api.model
    def get_workbench_data(self, warehouse_id=None):
        warehouse = self._get_warehouse(warehouse_id)
        types = self._get_workbench_types(warehouse)
        base = [("picking_type_id", "in", types.ids)] if types else [("id", "=", 0)]

        stats = []
        for key in STATUS_ORDER:
            stats.append(
                {
                    "key": key,
                    "label": STATUS_LABELS[key],
                    "color": STAT_COLORS.get(key, "all"),
                    "count": self._count(self._status_domain(key, base)),
                }
            )

        all_counts = self._counts_by_type(self._status_domain("all", base))
        type_payload = [
            self._type_payload(picking_type, all_counts.get(picking_type.id, 0))
            for picking_type in types
        ]
        ia_title, ia_subtitle, ia_color = TYPE_SEQUENCE_META["IA"]
        type_payload.append(
            {
                "id": False,
                "key": "ia",
                "name": ia_title,
                "display_name": ia_title,
                "subtitle": ia_subtitle,
                "color": ia_color,
                "count": self._inventory_pending_count(warehouse),
                "virtual": True,
            }
        )

        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        return {
            "user": {"name": self.env.user.name, "time": now.strftime("%H:%M")},
            "warehouses": [
                {"id": wh.id, "name": wh.name} for wh in self._get_warehouses()
            ],
            "selected_warehouse": (
                {"id": warehouse.id, "name": warehouse.name} if warehouse else False
            ),
            "stats": stats,
            "types": type_payload,
            "recent": [
                self._serialize_picking(picking)
                for picking in self._recent_pickings()
            ],
        }

    @api.model
    def get_workbench_list(
        self,
        warehouse_id,
        dimension,
        value,
        filter_value=None,
        page=1,
        page_size=80,
    ):
        warehouse = self._get_warehouse(warehouse_id)
        types = self._get_workbench_types(warehouse)
        type_ids = types.ids
        if not type_ids:
            return {
                "total": 0,
                "page": 1,
                "page_size": page_size,
                "records": [],
                "facets": [],
                "title": "",
                "subtitle": "",
            }

        base = [("picking_type_id", "in", type_ids)]
        filter_value = str(filter_value or "all")
        page = max(1, int(page or 1))
        page_size = min(200, max(1, int(page_size or 80)))

        if dimension == "type":
            if not str(value).isdigit() or int(value) not in type_ids:
                raise UserError(_("Invalid operation type."))
            picking_type = types.filtered(lambda item: item.id == int(value))
            base_type = Domain.AND(
                [base, [("picking_type_id", "=", picking_type.id)]]
            )
            domain = self._status_domain("all", base_type)
            total = self._count(domain)
            facets = [
                {
                    "key": "all",
                    "label": STATUS_LABELS["all"],
                    "count": total,
                    "color": STATUS_COLORS["all"],
                }
            ]
            for key in STATUS_ORDER[1:]:
                facets.append(
                    {
                        "key": key,
                        "label": STATUS_LABELS[key],
                        "count": self._count(self._status_domain(key, base_type)),
                        "color": STATUS_COLORS[key],
                    }
                )
            if filter_value != "all":
                if filter_value not in STATUS_ORDER:
                    raise UserError(_("Invalid status filter."))
                domain = Domain.AND(
                    [domain, self._status_domain(filter_value)]
                )
                total = self._count(domain)
            title, _subtitle, _color = self._type_meta(picking_type)
            subtitle_text = f"{self._type_subtitle_cn(picking_type)} · 作业入口"
        else:
            if value not in STATUS_ORDER:
                raise UserError(_("Invalid status filter."))
            fixed_domain = self._status_domain(value, base)
            total = self._count(fixed_domain)
            facets = [
                {
                    "key": "all",
                    "label": STATUS_LABELS["all"],
                    "count": total,
                    "color": STATUS_COLORS["all"],
                }
            ]
            for picking_type in types:
                facets.append(
                    {
                        "key": str(picking_type.id),
                        "label": self._type_meta(picking_type)[0],
                        "count": self._count(
                            Domain.AND(
                                [
                                    fixed_domain,
                                    [("picking_type_id", "=", picking_type.id)],
                                ]
                            )
                        ),
                        "color": self._type_meta(picking_type)[2],
                    }
                )
            domain = fixed_domain
            if filter_value != "all":
                if not filter_value.isdigit() or int(filter_value) not in type_ids:
                    raise UserError(_("Invalid operation type."))
                domain = Domain.AND(
                    [domain, [("picking_type_id", "=", int(filter_value))]]
                )
                total = self._count(domain)
            title = STATUS_LABELS[value]
            subtitle_text = (
                "全部单据 · 作业入口"
                if value == "all"
                else f"{STATUS_LABELS[value]}单据 · 作业入口"
            )

        pickings = self.env["stock.picking"].search(
            domain,
            order="priority desc, scheduled_date asc, id desc",
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "records": [self._serialize_picking(picking) for picking in pickings],
            "facets": facets,
            "title": title,
            "subtitle": subtitle_text,
            "domain": domain,
        }

    @api.model
    def select_warehouse(self, warehouse_id):
        warehouse = self._get_warehouse(warehouse_id)
        if not warehouse:
            raise UserError(_("No warehouse available."))
        self.env.user.sudo().write(
            {"barcode_workbench_warehouse_id": warehouse.id}
        )
        return self.get_workbench_data(warehouse.id)

    @api.model
    def create_empty_picking(self, warehouse_id, picking_type_id):
        """Create an empty transfer and open it in the scan app.

        Used by the workbench "+" action: the operator builds the transfer
        by scanning products (tracked or not) instead of pre-filling lines.
        """
        warehouse = self._get_warehouse(warehouse_id)
        types = self._get_workbench_types(warehouse)
        picking_type = types.filtered(
            lambda item: item.id == int(picking_type_id)
        )
        if not picking_type:
            raise UserError(_("Invalid operation type."))
        location = picking_type.default_location_src_id or warehouse.lot_stock_id
        location_dest = (
            picking_type.default_location_dest_id or warehouse.lot_stock_id
        )
        if not location or not location_dest:
            raise UserError(
                _(
                    "Set the default source and destination locations on "
                    "operation type %(type)s first.",
                    type=picking_type.name,
                )
            )
        picking = self.env["stock.picking"].create(
            {
                "picking_type_id": picking_type.id,
                "location_id": location.id,
                "location_dest_id": location_dest.id,
            }
        )
        # The transfer starts draft and is confirmed automatically once the
        # first scanned product creates its move (see the wizard).
        wizard = self.env["wiz.stock.barcodes.picking"].create(
            {
                "picking_id": picking.id,
                "allow_new_products": True,
            }
        )
        wizard._set_default_values()
        self.mark_recent(picking.id)
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_picking.action_picking_barcode_scan"
        )
        action["params"] = {"wiz_id": wizard.id}
        action["views"] = [(False, "list"), (False, "form")]
        return action

    @api.model
    def toggle_star(self, picking_id, starred):
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            raise UserError(_("The transfer no longer exists."))
        try:
            picking.check_access("write")
        except AccessError as error:
            raise UserError(_("You cannot update this transfer.")) from error
        picking.write({"priority": "1" if starred else "0"})
        return bool(starred)

    @api.model
    def mark_recent(self, picking_id):
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            return False
        Recent = self.env["stock.barcodes.picking.recent"]
        recent = Recent.search(
            [
                ("user_id", "=", self.env.user.id),
                ("picking_id", "=", picking.id),
            ],
            limit=1,
        )
        values = {"last_seen": fields.Datetime.now()}
        if recent:
            recent.write(values)
        else:
            Recent.create(
                {
                    "user_id": self.env.user.id,
                    "picking_id": picking.id,
                    **values,
                }
            )
        older = Recent.search(
            [("user_id", "=", self.env.user.id)],
            order="last_seen desc, id desc",
            offset=MAX_RECENT,
            limit=1000,
        )
        older.unlink()
        return True

    @api.model
    def scan_workbench_barcode(self, barcode, warehouse_id=None):
        """Resolve a scanned transfer / product / location barcode.

        Returns ``{"action": "open_picking" | "choose" | "error", ...}``.
        Only transfers of the selected warehouse's workbench types and not
        yet done/cancelled are considered.
        """
        barcode = (barcode or "").strip()
        if not barcode:
            return {"action": "error", "message": "请先扫描条码。"}
        warehouse = self._get_warehouse(warehouse_id)
        types = self._get_workbench_types(warehouse)
        if not types:
            return {
                "action": "error",
                "message": "当前仓库没有可用的作业类型。",
            }
        Picking = self.env["stock.picking"]
        base = [
            ("picking_type_id", "in", types.ids),
            ("state", "not in", ("done", "cancel")),
        ]

        pickings = Picking.search(base + [("name", "=", barcode)], limit=20)
        if not pickings:
            pickings = Picking.search(base + [("name", "ilike", barcode)], limit=20)

        if not pickings:
            location = self.env["stock.location"].search(
                [("barcode", "=", barcode)], limit=1
            )
            if location:
                pickings = Picking.search(
                    base
                    + [
                        "|",
                        ("location_id", "child_of", location.id),
                        ("location_dest_id", "child_of", location.id),
                    ],
                    limit=20,
                )

        if not pickings:
            product = self.env["product.product"].search(
                [("barcode", "=", barcode)], limit=1
            )
            if product:
                pickings = Picking.search(
                    base + [("move_ids.product_id", "=", product.id)], limit=20
                )

        if not pickings:
            return {
                "action": "error",
                "message": "未找到匹配的单据。",
            }
        if len(pickings) == 1:
            return {"action": "open_picking", "picking_id": pickings.id}
        return {
            "action": "choose",
            "picking_ids": pickings.ids,
            "candidates": [
                self._serialize_picking(picking) for picking in pickings
            ],
        }

    # ------------------------------------------------------------------
    # inventory count (IA card)
    # ------------------------------------------------------------------

    @api.model
    def _inventory_locations(self, warehouse):
        if not warehouse:
            return self.env["stock.location"]
        return self.env["stock.location"].search(
            [("warehouse_id", "=", warehouse.id), ("usage", "=", "internal")]
        )

    @api.model
    def _inventory_domain(self, warehouse):
        locations = self._inventory_locations(warehouse)
        if not locations:
            return [("id", "=", 0)]
        return [
            ("location_id", "in", locations.ids),
            ("inventory_date", "<=", fields.Date.today()),
        ]

    @api.model
    def _serialize_quant(self, quant):
        return {
            "id": quant.id,
            "product_id": quant.product_id.id,
            "product": quant.product_id.display_name,
            "location": quant.location_id.display_name,
            "lot": quant.lot_id.name or "",
            "quantity": quant.quantity,
            "inventory_quantity": quant.inventory_quantity,
            "diff": quant.inventory_diff_quantity,
            "uom": quant.product_uom_id.name or "",
        }

    @api.model
    def get_inventory_scan_data(self, warehouse_id=None):
        warehouse = self._get_warehouse(warehouse_id)
        domain = self._inventory_domain(warehouse)
        Quant = self.env["stock.quant"]
        pending_count = Quant.search_count(domain)
        quants = Quant.search(
            domain,
            order="location_id, product_id, id",
            limit=500,
        )
        return {
            "warehouse": (
                {"id": warehouse.id, "name": warehouse.name} if warehouse else False
            ),
            "pending_count": pending_count,
            "quants": [self._serialize_quant(quant) for quant in quants],
        }

    @api.model
    def scan_inventory_barcode(self, barcode, warehouse_id=None):
        barcode = (barcode or "").strip()
        if not barcode:
            return {"action": "error", "message": "请先扫描条码。"}
        warehouse = self._get_warehouse(warehouse_id)
        domain = self._inventory_domain(warehouse)
        Quant = self.env["stock.quant"]

        quants = Quant.browse()
        product = self.env["product.product"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if product:
            quants = Quant.search(
                domain + [("product_id", "=", product.id)],
                order="location_id, id",
                limit=50,
            )
        if not quants:
            lot = self.env["stock.lot"].search([("name", "=", barcode)], limit=1)
            if lot:
                quants = Quant.search(
                    domain + [("lot_id", "=", lot.id)],
                    order="location_id, id",
                    limit=50,
                )
        if not quants:
            location = self.env["stock.location"].search(
                [("barcode", "=", barcode)], limit=1
            )
            if location:
                quants = Quant.search(
                    domain + [("location_id", "child_of", location.id)],
                    order="product_id, id",
                    limit=50,
                )
        if not quants:
            return {"action": "error", "message": "未找到待盘点的库存。"}
        return {
            "action": "focus" if len(quants) == 1 else "choose",
            "quant_ids": quants.ids,
            "candidates": [self._serialize_quant(quant) for quant in quants],
        }

    @api.model
    def apply_inventory(self, entries, warehouse_id=None):
        warehouse = self._get_warehouse(warehouse_id)
        domain = self._inventory_domain(warehouse)
        allowed_ids = set(
            self.env["stock.quant"].search(domain).ids
        )
        Quant = self.env["stock.quant"]
        applied_ids = []
        for entry in entries or []:
            quant_id = int(entry.get("quant_id") or 0)
            if quant_id not in allowed_ids:
                raise UserError(_("This inventory line is no longer available."))
            quantity = entry.get("quantity")
            if quantity is None or quantity == "":
                continue
            quant = Quant.browse(quant_id).with_context(inventory_mode=True)
            quant.write({"inventory_quantity": float(quantity)})
            applied_ids.append(quant_id)
        if applied_ids:
            quants = Quant.browse(applied_ids).with_context(inventory_mode=True)
            quants._compute_inventory_diff_quantity()
            quants.action_apply_inventory()
        return {"applied": len(applied_ids)}
