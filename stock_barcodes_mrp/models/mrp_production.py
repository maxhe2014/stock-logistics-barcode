# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def action_barcode_scan(self):
        """Open the MRP scan client action (OWL MrpScanApp) for this MO.

        Returns an ir.actions.client (not the legacy act_window wizard form)
        so all barcode entry points converge on the OWL interface.
        """
        self.ensure_one()
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "production_id": self.id,
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            "res_id": self.id,
        })
        return {
            "type": "ir.actions.client",
            "tag": "stock_barcodes_mrp_scan_app",
            "params": {"wiz_id": wiz.id},
            "target": "fullscreen",
        }

    def action_open_scan_wizard(self):
        """Open the MRP scan client action from the list view.

        Handles two entry shapes from the MO list:
        - Header button (0 selected): scan-first mode — ``production_id``
          left empty; the operator scans a product barcode or SN first
          and the wizard reverse-looks-up the matching active MO (single
          match → switch directly; multi-match → flag is set and the
          client action auto-opens the filtered list via doAction).
        - Row button (1 selected): per-MO mode — ``production_id`` set
          to the row's MO, scan-first step is skipped.

        Returns an ``ir.actions.client`` pointing at the OWL
        ``MrpScanApp`` component (fullscreen).
        """
        production_id = self.id if len(self) == 1 else False
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            "production_id": production_id,
        })
        return {
            "type": "ir.actions.client",
            "tag": "stock_barcodes_mrp_scan_app",
            "params": {"wiz_id": wiz.id},
            "target": "fullscreen",
        }

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
