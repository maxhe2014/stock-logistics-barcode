# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class StockBarcodesPickingRecent(models.Model):
    """Last transfers opened by a user in the scan workbench."""

    _name = "stock.barcodes.picking.recent"
    _description = "Scan Workbench Recent Picking"
    _order = "last_seen desc, id desc"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        index=True,
        ondelete="cascade",
    )
    picking_id = fields.Many2one(
        "stock.picking",
        string="Transfer",
        required=True,
        index=True,
        ondelete="cascade",
    )
    last_seen = fields.Datetime(
        string="Last Seen",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    _sql_constraints = [
        (
            "uniq_user_picking",
            "unique(user_id, picking_id)",
            "A transfer can only appear once per user.",
        )
    ]
