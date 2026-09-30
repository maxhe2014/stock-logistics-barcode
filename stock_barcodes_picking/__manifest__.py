# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Barcodes Picking",
    "summary": "Barcode scanning for delivery orders (outgoing pickings)",
    "version": "19.0.1.0.0",
    "author": "OpenViking, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/stock-logistics-barcode",
    "license": "AGPL-3",
    "category": "Warehouse",
    "depends": ["barcodes", "stock", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_actions_client.xml",
        "wizard/stock_barcodes_picking_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_type_views.xml",
        "views/stock_location_views.xml",
    ],
    "assets": {
        "web.assets_web": [
            "stock_barcodes_picking/static/src/picking_scan_app.esm.js",
            "stock_barcodes_picking/static/src/picking_scan_app.xml",
            "stock_barcodes_picking/static/src/picking_scan_app.css",
        ],
    },
    "installable": True,
}
