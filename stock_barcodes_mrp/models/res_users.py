# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    mrp_workcenter_ids = fields.Many2many(
        "mrp.workcenter",
        string="Work Centers",
        help="Work centers this operator is assigned to. "
        "Used to filter the MRP barcode queue (My Work Orders).",
    )
