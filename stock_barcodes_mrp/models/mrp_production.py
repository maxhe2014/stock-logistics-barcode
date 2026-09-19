# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def action_barcode_scan(self):
        self.ensure_one()
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "production_id": self.id,
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            "res_id": self.id,
        })
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_mrp.action_stock_barcodes_mrp"
        )
        action["res_id"] = wiz.id
        return action
