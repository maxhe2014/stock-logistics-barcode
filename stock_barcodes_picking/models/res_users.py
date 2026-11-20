# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    barcode_workbench_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Scan Workbench Warehouse",
        domain="[('company_id', 'in', company_ids)]",
        help="Last warehouse selected in the barcode scan workbench.",
    )
