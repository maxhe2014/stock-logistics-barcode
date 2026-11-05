# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models


class PickingType(models.Model):
    _inherit = "stock.picking.type"

    # Keep the original manufacturing settings available without adding a
    # dependency on stock_barcodes_picking. Odoo merges these identical field
    # definitions when both addons are installed, preserving the stored values.
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
    barcode_mrp_lot_scan_policy = fields.Selection(
        string="Force Lot/Serial scan?",
        selection=[
            ("mandatory", "Mandatory Scan"),
            ("optional", "Optional Scan"),
        ],
        default="mandatory",
        required=True,
        help="Mandatory Scan requires scanning every component lot/serial "
             "number. Optional Scan lets the operator consume reserved "
             "lots/serials with the line buttons or by confirming a "
             "component quantity without scanning its lot/serial.",
    )
