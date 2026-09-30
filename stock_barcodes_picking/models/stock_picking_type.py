# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class PickingType(models.Model):
    _inherit = "stock.picking.type"

    barcode_scan_source_location = fields.Boolean(
        string="Scan Source Location",
        default=True,
        help="If enabled, the barcode scan flow requires the operator to "
             "scan the source location barcode. If disabled, the "
             "picking's default source location is used automatically.",
    )
    barcode_scan_dest_location = fields.Boolean(
        string="Scan Destination Location",
        default=False,
        help="If enabled, the barcode scan flow requires the operator to "
             "scan the destination location barcode. If disabled, the "
             "picking's default destination location is used "
             "automatically.",
    )
