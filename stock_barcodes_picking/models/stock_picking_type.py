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
    barcode_show_reserved_sns = fields.Boolean(
        string="Show Reserved Serial Numbers",
        default=True,
        help="If enabled, reserved (but not yet picked) serial numbers are "
             "displayed in the barcode scanner so the picker knows which "
             "serial numbers to scan.",
    )
    barcode_require_pack = fields.Selection(
        string="Force put in package",
        selection=[
            ("mandatory", "After Each Product"),
            ("optional", "After a Group of Products"),
            ("no", "No Requirement"),
        ],
        default="no",
        help="If 'After Each Product', a package is mandatory after each "
             "product is scanned. If 'After a Group of Products', packages "
             "are optional but all products must be packed before validation.",
    )
    barcode_validation_all_packed = fields.Boolean(
        string="Require All Products Packed Before Validation",
        default=False,
        help="If enabled, all picked products must be put into a package "
             "before the transfer can be validated. (Requires 'After a Group "
             "of Products' or 'After Each Product'.)",
    )
