# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import models


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def action_barcode_scan(self):
        """Open the MRP scan client action (OWL MrpScanApp) for this WO.

        Returns an ir.actions.client (not the legacy act_window wizard form)
        so all barcode entry points converge on the OWL interface.
        """
        self.ensure_one()
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "production_id": self.production_id.id,
            "workorder_id": self.id,
            "res_model_id": self.env.ref("mrp.model_mrp_workorder").id,
            "res_id": self.id,
        })
        return {
            "type": "ir.actions.client",
            "tag": "stock_barcodes_mrp_scan_app",
            "params": {"wiz_id": wiz.id},
            "target": "fullscreen",
        }
