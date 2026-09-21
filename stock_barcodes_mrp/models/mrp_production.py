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

    def action_open_scan_wizard(self):
        """Scan-first entry from the MO list header button.

        Opens the barcode wizard WITHOUT a preselected MO — the operator
        scans a product barcode or SN first, and the wizard reverse-
        looks-up the matching active MO (single match -> switch directly;
        multi-match -> sets the visible_switch_selector flag and the
        operator clicks the 'View candidate MOs' button to open the
        filtered list).

        NB: only one record (or none) is expected on entry — the header
        button doesn't require a selection. The 'Scan' row button on
        each MO row uses action_barcode_scan (the existing per-MO entry)
        instead.
        """
        # `self` may be empty when invoked from the header button without
        # a selected row — that's the scan-first case.
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            # production_id 留空 — scan-first 模式
        })
        action = self.env["ir.actions.actions"]._for_xml_id(
            "stock_barcodes_mrp.action_stock_barcodes_mrp"
        )
        action["res_id"] = wiz.id
        return action

    def action_open_mrp_barcode(self):
        """Open the MRP barcode scanning wizard for this production order.

        Used by the work-order queue tree view inside the barcode wizard.
        """
        return self.action_barcode_scan()

    def action_switch_to_in_barcode(self):
        """Switch the *currently open* barcode wizard to this MO.

        Called from the ambiguous-MO selection list embedded in the wizard
        form. The wizard id is passed explicitly as ``barcode_wizard_id``
        in the context — it must NOT use ``active_id``: inside a wizard
        opened with target=new, active_id points at the parent record, not
        at the wizard itself.
        """
        self.ensure_one()
        wizard_id = self.env.context.get("barcode_wizard_id")
        wiz = (
            self.env["wiz.stock.barcodes.mrp"]
            .browse(wizard_id)
            .exists()
            if wizard_id
            else self.env["wiz.stock.barcodes.mrp"]
        )
        if wiz:
            # _switch_production sets the banner: notice + next instruction.
            wiz._switch_production(self)
            return True
        # No wizard in context (e.g. direct invocation) -> open a fresh one.
        return self.action_open_mrp_barcode()
