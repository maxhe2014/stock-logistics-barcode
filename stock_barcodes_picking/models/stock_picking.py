# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def action_barcode_scan(self):
        """Open the barcode scanning wizard for this picking.

        Reads the ``ir.actions.client`` record
        (``stock_barcodes_picking.action_picking_barcode_scan``) and
        merges the runtime ``wiz_id`` into ``params``. The ``views`` key
        is set explicitly because the dict is returned directly (not via
        the call_button endpoint whose ``clean_action`` would inject it);
        without it ``_preprocessAction`` reads ``action.views.map`` and
        crashes.
        """
        self.ensure_one()
        wiz = self.env["wiz.stock.barcodes.picking"].create(
            {"picking_id": self.id}
        )
        wiz._set_default_values()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_picking.action_picking_barcode_scan"
        )
        action["params"] = {"wiz_id": wiz.id}
        action["views"] = [(False, "list"), (False, "form")]
        return action
