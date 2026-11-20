# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Barcodes Picking Batch",
    "summary": "Batch transfer scanning for the barcode workbench",
    "version": "19.0.1.0.0",
    "author": "OpenViking, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/stock-logistics-barcode",
    "license": "AGPL-3",
    "category": "Warehouse",
    "depends": ["stock_barcodes_picking", "stock_picking_batch"],
    "data": [
        "data/ir_actions_client.xml",
    ],
    "assets": {
        "web.assets_web": [
            "stock_barcodes_picking_batch/static/src/batch/batch_workbench.js",
            "stock_barcodes_picking_batch/static/src/batch/batch_workbench.xml",
            "stock_barcodes_picking_batch/static/src/batch/batch_workbench.scss",
            "stock_barcodes_picking_batch/static/src/scan/batch_scan_patch.js",
            "stock_barcodes_picking_batch/static/src/scan/batch_scan_templates.xml",
            "stock_barcodes_picking_batch/static/src/scan/batch_scan.scss",
        ],
        "web.assets_web_dark": [
            "stock_barcodes_picking_batch/static/src/batch/batch_workbench.dark.scss",
        ],
    },
    "installable": True,
}
