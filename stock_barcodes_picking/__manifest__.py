# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Barcodes Picking",
    "summary": "Barcode scanning for delivery orders (outgoing pickings)",
    "version": "19.0.2.0.0",
    "author": "OpenViking, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/stock-logistics-barcode",
    "license": "AGPL-3",
    "category": "Warehouse",
    "depends": ["barcodes", "stock", "web"],
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "data": [
        "security/ir.model.access.csv",
        "security/stock_barcodes_picking_rules.xml",
        "data/ir_actions_client.xml",
        "wizard/stock_barcodes_picking_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_type_views.xml",
        "views/stock_location_views.xml",
    ],
    "assets": {
        "web.assets_web": [
            "stock_barcodes_picking/static/src/picking_scan_app.js",
            "stock_barcodes_picking/static/src/picking_scan_app.xml",
            "stock_barcodes_picking/static/src/picking_scan_app.css",
            "stock_barcodes_picking/static/src/shared/scan_ui.scss",
            "stock_barcodes_picking/static/src/picking_scan_app.scss",
            "stock_barcodes_picking/static/src/workbench/scan_workbench.js",
            "stock_barcodes_picking/static/src/workbench/scan_workbench.xml",
            "stock_barcodes_picking/static/src/workbench/scan_workbench.scss",
            "stock_barcodes_picking/static/src/workbench/open_apps_menu.js",
        ],
        "web.assets_web_dark": [
            "stock_barcodes_picking/static/src/shared/scan_ui.dark.scss",
            "stock_barcodes_picking/static/src/picking_scan_app.dark.scss",
            "stock_barcodes_picking/static/src/workbench/scan_workbench.dark.scss",
        ],
    },
    "installable": True,
}
