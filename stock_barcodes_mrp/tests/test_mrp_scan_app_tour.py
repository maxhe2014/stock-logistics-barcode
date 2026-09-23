# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import Command
from odoo.tests import Form, HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMrpScanAppTour(HttpCase):
    """Tour-based tests for the OWL MrpScanApp client action.

    Verifies the two B1 路线 promises end-to-end through the browser:
    1. Single-match scan-first: scan a product barcode that uniquely
       matches one active MO — the MO info strip must update.
    2. Multi-match scan-first: scan a product barcode that matches
       multiple active MOs — the client auto-doActions into the
       filtered mrp.production list (no extra button click — the
       onchange-can't-return-action trade-off is gone).
    """

    @classmethod
    def setUpClassProducts(cls):
        """Create two finished products with distinct barcodes."""
        Product = cls.env["product.product"]
        cls.product_single = Product.create({
            "name": "SingleMatchProduct",
            "type": "consu",
            "barcode": "SINGLE_BARCODE_001",
        })
        cls.product_multi = Product.create({
            "name": "MultiMatchProduct",
            "type": "consu",
            "barcode": "MULTI_BARCODE_001",
        })

    @classmethod
    def _make_bom_and_mo(cls, product, qty=1.0, components=None):
        """Create a confirmed MO for ``product`` with the given
        component lines (list of (product, qty) tuples). Returns the
        MO record."""
        Bom = cls.env["mrp.bom"]
        bom_vals = {
            "product_id": product.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "product_qty": qty,
            "type": "normal",
            "bom_line_ids": [
                Command.create({"product_id": p.id, "product_qty": q})
                for p, q in (components or [])
            ],
        }
        bom = Bom.create(bom_vals)
        with Form(
            cls.env["mrp.production"].with_context(default_product_id=product.id)
        ) as f:
            f.product_id = product
            f.bom_id = bom
            f.product_qty = qty
        mo = f.save()
        mo.action_confirm()
        return mo

    def _open_mo_list(self):
        """Return the URL that opens the MO list view (the entry
        point for the Scan header button)."""
        action = self.env.ref("mrp.mrp_production_action")
        return f"/odoo/action-{action.xml_id}"

    def test_01_single_match_tour(self):
        """Single-match: scan product barcode -> MO info strip updates."""
        self.setUpClassProducts()
        # A component is needed so the BOM is valid.
        component = self.env["product.product"].create({
            "name": "SingleMatchComp",
            "type": "consu",
        })
        mo = self._make_bom_and_mo(
            self.product_single,
            qty=1.0,
            components=[(component, 1.0)],
        )
        self.assertEqual(mo.state, "confirmed")

        self.start_tour(
            self._open_mo_list(),
            "mrp_scan_app_single_match",
            login="admin",
            timeout=120,
        )

    def test_02_multi_match_tour(self):
        """Multi-match: scan product barcode -> auto-doAction into
        the filtered mrp.production list."""
        self.setUpClassProducts()
        component = self.env["product.product"].create({
            "name": "MultiMatchComp",
            "type": "consu",
        })
        mo1 = self._make_bom_and_mo(
            self.product_multi,
            qty=1.0,
            components=[(component, 1.0)],
        )
        mo2 = self._make_bom_and_mo(
            self.product_multi,
            qty=1.0,
            components=[(component, 1.0)],
        )
        self.assertEqual({mo1.state, mo2.state}, {"confirmed"})

        self.start_tour(
            self._open_mo_list(),
            "mrp_scan_app_multi_match",
            login="admin",
            timeout=120,
        )

    def test_03_finished_sn_display_and_clear(self):
        """Serial finished SN scan → display row appears. Clear → gone.

        Verifies the finished-SN display strip (`.o_mrp_scan_finished_sn`)
        shows the bound SN and the Clear SN button unbinds it.
        """
        Product = self.env["product.product"]
        finished = Product.create({
            "name": "SerialFinishedProduct",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "SERIAL_FP_BARCODE_001",
        })
        component = Product.create({
            "name": "SerialFpComp",
            "type": "consu",
        })
        self._make_bom_and_mo(finished, qty=1.0, components=[(component, 1.0)])

        self.start_tour(
            self._open_mo_list(),
            "mrp_scan_app_finished_sn_display",
            login="admin",
            timeout=120,
        )
