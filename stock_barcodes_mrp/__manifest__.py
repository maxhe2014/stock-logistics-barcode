# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
{
    "name": "Stock Barcodes MRP",
    "summary": "Barcode scanning for manufacturing orders and material traceability",
    "version": "19.0.1.5.0",
    "author": "OpenViking, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/stock-logistics-barcode",
    "license": "AGPL-3",
    "category": "Manufacturing",
    "depends": ["barcodes", "mrp", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "wizard/stock_barcodes_mrp_views.xml",
        "views/mrp_production_views.xml",
        "views/mrp_workorder_views.xml",
        "report/stock_lot_traceability_report.xml",
        "views/stock_lot_views.xml",
    ],
    "installable": True,
}
