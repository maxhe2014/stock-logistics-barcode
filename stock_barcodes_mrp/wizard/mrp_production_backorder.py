# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import models


class MrpProductionBackorder(models.TransientModel):
    _inherit = "mrp.production.backorder"

    def action_backorder(self):
        """After creating the backorder MO, redirect to the scan app.

        ``super()`` calls ``button_mark_done(skip_backorder=True,
        mo_ids_to_backorder=...)`` which splits the MO and returns an
        act_window opening the backorder form. We replace that with the
        OWL scan client action pre-bound to the new backorder MO so the
        operator keeps scanning without leaving the barcode interface.
        """
        res = super().action_backorder()
        return self._redirect_to_scan_app(res)

    def action_close_mo(self):
        """No new backorder from lines, but ``always_backorder_mo_ids``
        may still create one. Redirect to the scan app if so."""
        res = super().action_close_mo()
        return self._redirect_to_scan_app(res)

    def _redirect_to_scan_app(self, res):
        """Find the newly created backorder MO and open the scan app.

        Falls back to ``res`` (the core act_window) when no backorder
        was created (e.g. full production or create_backorder='never').
        """
        original = self.mrp_production_ids[:1]
        if not original or not original.production_group_id:
            return res
        backorders = self.env["mrp.production"].search([
            ("production_group_id", "=", original.production_group_id.id),
            ("id", "!=", original.id),
            ("state", "in", ("confirmed", "progress", "to_close")),
        ], order="id desc", limit=1)
        if backorders:
            return backorders.action_barcode_scan()
        return res
