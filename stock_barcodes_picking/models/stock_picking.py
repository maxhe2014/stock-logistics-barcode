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

    def action_open_scan_wizard(self):
        """Open the barcode scan client action from list/kanban views.

        Two entry shapes:
        - Header button (0 selected): scan-first mode — ``picking_id``
          left empty; the operator scans a transfer name to select a
          picking.
        - Row/card button (1 selected): per-picking mode — ``picking_id``
          set to the row's picking, scan the source location next.

        Returns an ``ir.actions.client`` pointing at the OWL
        ``PickingScanApp`` component (fullscreen).
        """
        picking_id = self.id if len(self) == 1 else False
        wiz = self.env["wiz.stock.barcodes.picking"].create(
            {"picking_id": picking_id}
        )
        if picking_id:
            wiz._set_default_values()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_picking.action_picking_barcode_scan"
        )
        action["params"] = {"wiz_id": wiz.id}
        action["views"] = [(False, "list"), (False, "form")]
        return action
