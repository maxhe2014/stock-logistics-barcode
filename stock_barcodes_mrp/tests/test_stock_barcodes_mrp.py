# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo.tests.common import TransactionCase


class TestStockBarcodesMrp(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        group_production_lot = cls.env.ref("stock.group_production_lot")
        cls.env.user.group_ids = [(4, group_production_lot.id)]

        cls.StockLocation = cls.env["stock.location"]
        cls.Product = cls.env["product.product"]
        cls.StockProductionLot = cls.env["stock.lot"]
        cls.StockQuant = cls.env["stock.quant"]
        cls.MrpBom = cls.env["mrp.bom"]
        cls.MrpProduction = cls.env["mrp.production"]
        cls.MrpWorkorder = cls.env["mrp.workorder"]
        cls.WizScanMrp = cls.env["wiz.stock.barcodes.mrp"]

        cls.company = cls.env.company
        cls.warehouse = cls.env.ref("stock.warehouse0")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")

        # Source location for components (with barcode)
        cls.components_location = cls.StockLocation.create({
            "name": "Components Shelf",
            "usage": "internal",
            "location_id": cls.stock_location.id,
            "barcode": "LOC-COMP-001",
        })

        # Finished products location
        cls.finished_location = cls.StockLocation.create({
            "name": "Finished Goods",
            "usage": "internal",
            "location_id": cls.stock_location.id,
            "barcode": "LOC-FIN-001",
        })

        # Finished product (no tracking for phase 1)
        cls.finished_product = cls.Product.create({
            "name": "Finished Product A",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-FIN-A",
        })

        # Component product with lot tracking
        cls.component_tracked = cls.Product.create({
            "name": "Component Tracked",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-COMP-T",
        })

        # Component product without tracking
        cls.component_simple = cls.Product.create({
            "name": "Component Simple",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-COMP-S",
        })

        # Lot for tracked component
        cls.component_lot = cls.StockProductionLot.create({
            "name": "LOT-COMP-001",
            "product_id": cls.component_tracked.id,
            "company_id": cls.company.id,
        })

        # Quants: stock the components
        cls.StockQuant.create({
            "product_id": cls.component_tracked.id,
            "lot_id": cls.component_lot.id,
            "location_id": cls.components_location.id,
            "quantity": 100.0,
        })
        cls.StockQuant.create({
            "product_id": cls.component_simple.id,
            "location_id": cls.components_location.id,
            "quantity": 100.0,
        })

        # BOM: 1 finished product = 2 tracked + 3 simple
        cls.bom = cls.MrpBom.create({
            "product_id": cls.finished_product.id,
            "product_tmpl_id": cls.finished_product.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {
                    "product_id": cls.component_tracked.id,
                    "product_qty": 2.0,
                    "product_uom_id": cls.component_tracked.uom_id.id,
                }),
                (0, 0, {
                    "product_id": cls.component_simple.id,
                    "product_qty": 3.0,
                    "product_uom_id": cls.component_simple.uom_id.id,
                }),
            ],
        })

        # Create and confirm an MO
        cls.production = cls.MrpProduction.create({
            "product_id": cls.finished_product.id,
            "product_qty": 1.0,
            "bom_id": cls.bom.id,
            "location_src_id": cls.components_location.id,
            "location_dest_id": cls.finished_location.id,
        })
        cls.production.action_confirm()

        # Tracked finished product (for phase 2 tests)
        cls.finished_product_tracked = cls.Product.create({
            "name": "Finished Product Tracked",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-FIN-T",
        })
        cls.finished_lot = cls.StockProductionLot.create({
            "name": "LOT-FIN-001",
            "product_id": cls.finished_product_tracked.id,
            "company_id": cls.company.id,
        })
        cls.bom_tracked = cls.MrpBom.create({
            "product_id": cls.finished_product_tracked.id,
            "product_tmpl_id": cls.finished_product_tracked.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {
                    "product_id": cls.component_tracked.id,
                    "product_qty": 2.0,
                    "product_uom_id": cls.component_tracked.uom_id.id,
                }),
                (0, 0, {
                    "product_id": cls.component_simple.id,
                    "product_qty": 3.0,
                    "product_uom_id": cls.component_simple.uom_id.id,
                }),
            ],
        })
        cls.production_tracked = cls.MrpProduction.create({
            "product_id": cls.finished_product_tracked.id,
            "product_qty": 1.0,
            "bom_id": cls.bom_tracked.id,
            "location_src_id": cls.components_location.id,
            "location_dest_id": cls.finished_location.id,
        })
        cls.production_tracked.action_confirm()

        # Serial finished product (Direction B: scan-time MO write)
        cls.finished_product_serial = cls.Product.create({
            "name": "Finished Product Serial",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-FIN-SER-T6",
        })
        cls.finished_lot_serial = cls.StockProductionLot.create({
            "name": "SN-SER-EXIST-001",
            "product_id": cls.finished_product_serial.id,
            "company_id": cls.company.id,
        })
        cls.bom_serial = cls.MrpBom.create({
            "product_id": cls.finished_product_serial.id,
            "product_tmpl_id": cls.finished_product_serial.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [
                (0, 0, {
                    "product_id": cls.component_simple.id,
                    "product_qty": 1.0,
                    "product_uom_id": cls.component_simple.uom_id.id,
                }),
            ],
        })
        cls.production_serial = cls.MrpProduction.create({
            "product_id": cls.finished_product_serial.id,
            "product_qty": 3.0,
            "bom_id": cls.bom_serial.id,
            "location_src_id": cls.components_location.id,
            "location_dest_id": cls.finished_location.id,
        })
        cls.production_serial.action_confirm()
        cls.production_serial.action_assign()

    def action_barcode_scanned(self, wizard, barcode):
        """Simulate scanning a barcode."""
        wizard._barcode_scanned = barcode
        wizard._on_barcode_scanned()

    def test_01_scan_component_without_tracking(self):
        """Test scanning a non-tracked component and confirming consumption."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        # Scan source location
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertEqual(wiz.location_id, self.components_location)
        # Scan product (simple component)
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        self.assertEqual(wiz.product_id, self.component_simple)
        # Set quantity and confirm
        wiz.product_qty = 3.0
        res = wiz.action_confirm()
        self.assertTrue(res)
        # Verify move line was created with correct quantity
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        self.assertEqual(move.move_line_ids.quantity, 3.0)

    def test_02_scan_component_with_lot(self):
        """Test scanning a tracked component with lot."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        # Scan source location
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertEqual(wiz.location_id, self.components_location)
        # Scan product (tracked component)
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.assertEqual(wiz.product_id, self.component_tracked)
        # Scan lot
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        self.assertEqual(wiz.lot_id, self.component_lot)
        # Set quantity and confirm
        wiz.product_qty = 2.0
        res = wiz.action_confirm()
        self.assertTrue(res)
        # Verify move line was created with correct quantity and lot
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        self.assertEqual(move.move_line_ids.quantity, 2.0)
        self.assertEqual(move.move_line_ids.lot_id, self.component_lot)

    def test_03_scan_non_component_product(self):
        """Test scanning a product that is not a component of the MO."""
        other_product = self.Product.create({
            "name": "Other Product",
            "type": "consu",
            "tracking": "none",
            "barcode": "PROD-OTHER",
        })
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-OTHER")
        self.assertEqual(wiz.product_id, other_product)
        wiz.product_qty = 1.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")

    def test_04_action_barcode_scan_from_production(self):
        """Test the action_barcode_scan entry point on mrp.production."""
        action = self.production.action_barcode_scan()
        # All entry points now return the OWL client action (not the
        # legacy act_window wizard form).
        self.assertEqual(action["type"], "ir.actions.client")
        self.assertEqual(action["tag"], "stock_barcodes_mrp_scan_app")
        wiz = self.WizScanMrp.browse(action["params"]["wiz_id"])
        self.assertEqual(wiz.production_id, self.production)
        self.assertEqual(wiz.location_id, self.components_location)

    def test_05_create_new_lot_via_scan(self):
        """Test creating a new lot by scanning an unknown lot barcode."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        # Scan a non-existent lot barcode
        self.action_barcode_scanned(wiz, "LOT-NEW-999")
        self.assertFalse(wiz.lot_id)
        self.assertEqual(wiz.lot_name, "LOT-NEW-999")
        wiz.product_qty = 2.0
        res = wiz.action_confirm()
        self.assertTrue(res)
        # Verify lot was created in database (wizard cleans lot_id after confirm)
        new_lot = self.StockProductionLot.search([
            ("name", "=", "LOT-NEW-999"),
            ("product_id", "=", self.component_tracked.id),
        ])
        self.assertTrue(new_lot)
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        # Filter move lines by the new lot (other tests may have added lines with different lots)
        new_lot_line = move.move_line_ids.filtered(lambda l: l.lot_id == new_lot)
        self.assertEqual(new_lot_line.lot_id, new_lot)

    def test_06_quantity_exceeds_demand(self):
        """Test that scanning more than demand shows force done option."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        # Try to scan more than the BOM demand (3.0)
        wiz.product_qty = 10.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertTrue(wiz.visible_force_done)
        # Force done should work
        res = wiz.action_force_done()
        self.assertTrue(res)
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        self.assertEqual(move.move_line_ids.quantity, 10.0)

    def test_07_scan_finished_lot(self):
        """Test scanning a finished product lot on a tracked MO."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        # Wizard should start at step 0 (finished product is tracked)
        self.assertEqual(wiz.step, 0)
        # Scan existing finished lot
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        self.assertEqual(wiz.finished_lot_id, self.finished_lot)
        self.assertEqual(wiz.finished_lot_name, "LOT-FIN-001")
        # Set qty and apply
        wiz.finished_qty_producing = 1.0
        res = wiz.action_apply_finished_lot()
        self.assertTrue(res)
        # Verify MO was updated
        self.assertEqual(self.production_tracked.qty_producing, 1.0)
        self.assertIn(self.finished_lot.id, self.production_tracked.lot_producing_ids.ids)
        # Wizard should now be at step 1
        self.assertEqual(wiz.step, 1)

    def test_08_create_new_finished_lot(self):
        """Test creating a new finished lot by manually entering lot name."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        # Manually enter a new lot name (not via scan, since unknown barcodes
        # fall through to location/product/lot dispatch)
        self.assertFalse(wiz.finished_lot_id)
        wiz.finished_lot_name = "LOT-FIN-NEW-999"
        # Set qty and apply
        wiz.finished_qty_producing = 2.0
        res = wiz.action_apply_finished_lot()
        self.assertTrue(res)
        # Verify lot was created and applied
        new_lot = self.StockProductionLot.search([
            ("name", "=", "LOT-FIN-NEW-999"),
            ("product_id", "=", self.finished_product_tracked.id),
        ])
        self.assertTrue(new_lot)
        self.assertEqual(self.production_tracked.qty_producing, 2.0)
        self.assertIn(new_lot.id, self.production_tracked.lot_producing_ids.ids)

    def test_09_guided_mode_tracked_starts_step0(self):
        """Test that guided mode starts at step 0 for tracked finished product."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        self.assertEqual(wiz.message_step, "Scan finished product lot")
        # For non-tracked product, should start at step 1
        wiz2 = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.assertEqual(wiz2.step, 1)
        self.assertEqual(
            wiz2.message_step,
            "Scan source location (or scan component directly)",
        )

    def test_10_traceability_finished_to_material(self):
        """Test bidirectional traceability: finished lot → consumed material lots."""
        # Set up: scan finished lot and consume tracked material lot on MO
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        # Apply finished lot
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        wiz.finished_qty_producing = 1.0
        res = wiz.action_apply_finished_lot()
        self.assertTrue(res)
        # Consume tracked material lot
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        wiz.product_qty = 2.0
        res = wiz.action_confirm()
        self.assertTrue(res)
        # Forward traceability: finished lot → consumed material lots
        self.finished_lot.invalidate_recordset()
        self.assertIn(self.component_lot.id, self.finished_lot.consumed_lot_ids.ids)
        self.assertGreater(self.finished_lot.consumed_lot_count, 0)

    def test_11_traceability_material_to_finished(self):
        """Test bidirectional traceability: material lot → produced finished lots."""
        # Set up: same as test_10 (scan finished lot + consume material lot)
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        wiz.finished_qty_producing = 1.0
        wiz.action_apply_finished_lot()
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        wiz.product_qty = 2.0
        wiz.action_confirm()
        # Backward traceability: material lot → produced finished lots
        self.component_lot.invalidate_recordset()
        self.assertIn(self.finished_lot.id, self.component_lot.produced_lot_ids.ids)
        self.assertGreater(self.component_lot.produced_lot_count, 0)

    def test_12_workorder_barcode_scan(self):
        """Test launching barcode scan from a workorder."""
        # Create a workorder for the tracked production
        workcenter = self.env["mrp.workcenter"].create({"name": "WC-TEST-001"})
        workorder = self.MrpWorkorder.create({
            "production_id": self.production_tracked.id,
            "name": "WO-TEST-001",
            "workcenter_id": workcenter.id,
        })
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
            "workorder_id": workorder.id,
        })
        self.assertEqual(wiz.workorder_id, workorder)
        self.assertEqual(wiz.production_id, self.production_tracked)
        # Scanning should still work via the workorder-linked wizard
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertEqual(wiz.location_id, self.components_location)
        # Location barcode must never become a finished lot on a tracked MO
        self.assertFalse(wiz.finished_lot_id)
        self.assertFalse(wiz.finished_lot_name)
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        self.assertEqual(wiz.product_id, self.component_simple)
        wiz.product_qty = 3.0
        res = wiz.action_confirm()
        self.assertTrue(res)

    def test_13_mo_done_state_rejects_scan(self):
        """Test that scanning is rejected when MO is done."""
        # Mark the simple production as done
        self.production.action_confirm()
        # Produce the required qty
        produce_wiz = self.env["mrp.production.backorder"].create({
            "production_id": self.production.id,
        }) if False else None  # Simplified: just check state guard
        # Instead, directly test the state check by creating a done MO
        done_mo = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        done_mo.action_confirm()
        done_mo.button_mark_done()
        self.assertEqual(done_mo.state, "done")
        wiz = self.WizScanMrp.create({
            "production_id": done_mo.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.product_qty = 1.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")

    def test_14_zero_quantity_rejected(self):
        """Test that zero quantity is rejected."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.product_qty = 0.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")

    def test_15_negative_quantity_rejected(self):
        """Test that negative quantity is rejected."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.product_qty = -5.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")

    def _scan_component(self, mo, product, barcode, qty, lot_barcode=None):
        wiz = self.WizScanMrp.create({"production_id": mo.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, barcode)
        if lot_barcode:
            self.action_barcode_scanned(wiz, lot_barcode)
        wiz.product_qty = qty
        return wiz, wiz.action_confirm()

    def test_16_new_lot_substitution_redistributes(self):
        """Consuming a different lot than the reserved one redistributes demand.

        The tracked component demand is 2, reserved to LOT-COMP-001. Scanning
        a brand-new lot with qty 2 must release the reserved line instead of
        silently consuming 4 units total.
        """
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 2.0)
        wiz, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 2.0, lot_barcode="LOT-SUBST-001",
        )
        self.assertTrue(res)
        new_lot = self.StockProductionLot.search([
            ("name", "=", "LOT-SUBST-001"),
            ("product_id", "=", self.component_tracked.id),
        ])
        self.assertTrue(new_lot)
        # Total consumed stays at demand (2), all on the new lot
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 2.0)
        self.assertEqual(
            move.move_line_ids.filtered(lambda l: l.lot_id == new_lot).quantity,
            2.0,
        )
        self.assertFalse(
            move.move_line_ids.filtered(lambda l: l.lot_id == self.component_lot)
        )

    def test_17_multi_lot_split_consumption(self):
        """Demand can be split across the reserved lot and a new lot."""
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        # First consume 1 from the reserved lot
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 1.0, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        # Then consume 1 from a new lot
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 1.0, lot_barcode="LOT-SPLIT-001",
        )
        self.assertTrue(res)
        new_lot = self.StockProductionLot.search([
            ("name", "=", "LOT-SPLIT-001"),
            ("product_id", "=", self.component_tracked.id),
        ])
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 2.0)
        self.assertEqual(
            move.move_line_ids.filtered(
                lambda l: l.lot_id == self.component_lot
            ).quantity,
            1.0,
        )
        self.assertEqual(
            move.move_line_ids.filtered(lambda l: l.lot_id == new_lot).quantity,
            1.0,
        )

    def test_18_new_lot_over_consumption_requires_force(self):
        """A new lot qty above total demand is blocked unless force done."""
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        wiz, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 3.0, lot_barcode="LOT-OVER-001",
        )
        self.assertFalse(res)
        self.assertTrue(wiz.visible_force_done)
        # The new lot was created but no move line yet
        self.assertFalse(
            move.move_line_ids.filtered(
                lambda l: l.lot_name == "LOT-OVER-001"
            )
        )
        # Force consumes 3 and releases the reserved 2
        self.assertTrue(wiz.action_force_done())
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 3.0)

    def test_19_reapply_different_finished_lot_replaces(self):
        """Applying a second finished lot replaces the first (no UserError).

        Core constrains lot-tracked products to max 1 lot in
        lot_producing_ids; the wizard must use replace semantics.
        """
        lot_b = self.StockProductionLot.create({
            "name": "LOT-FIN-002",
            "product_id": self.finished_product_tracked.id,
            "company_id": self.company.id,
        })
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        wiz.finished_qty_producing = 1.0
        self.assertTrue(wiz.action_apply_finished_lot())
        # Re-apply with a different lot
        wiz2 = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        wiz2.finished_lot_id = lot_b
        wiz2.finished_qty_producing = 1.0
        self.assertTrue(wiz2.action_apply_finished_lot())
        self.assertEqual(
            self.production_tracked.lot_producing_ids.ids, [lot_b.id]
        )

    def test_20_set_on_split_reservation_no_overflow(self):
        """SET on a multi-line reservation must not exceed total demand."""
        move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        # Split the single reserved line (qty 3) into two lines of 1.5
        line = move.move_line_ids[:1]
        line.quantity = 1.5
        self.env["stock.move.line"].create({
            "move_id": move.id,
            "product_id": self.component_simple.id,
            "product_uom_id": self.component_simple.uom_id.id,
            "quantity": 1.5,
            "location_id": self.components_location.id,
            "location_dest_id": line.location_dest_id.id,
        })
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 3.0)
        # Scan 2.0: SET first line to 2 must absorb 0.5 from the second
        wiz, res = self._scan_component(
            self.production, self.component_simple, "PROD-COMP-S", 2.0,
        )
        self.assertTrue(res)
        self.assertEqual(sum(move.move_line_ids.mapped("quantity")), 3.0)
        self.assertEqual(len(move.move_line_ids), 2)
        self.assertEqual(
            sorted(move.move_line_ids.mapped("quantity")), [1.0, 2.0]
        )

    def test_21_finish_tracked_without_lot_rejected(self):
        """Finishing a tracked MO without any finished lot is rejected."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        res = wiz.action_finish_production()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")
        self.assertNotEqual(self.production_tracked.state, "done")

    def test_21b_apply_wrong_product_lot_rejected(self):
        """A finished lot belonging to another product is rejected.

        The finished_lot_id picker cannot be domain-restricted client-side
        (a field-level dynamic domain crashed stock.lot search_read), so the
        server guard is the last line of defence.
        """
        wrong_lot = self.StockProductionLot.create({
            "name": "LOT-WRONG-PRODUCT",
            "product_id": self.component_tracked.id,
            "company_id": self.company.id,
        })
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        wiz.finished_lot_id = wrong_lot
        wiz.finished_qty_producing = 1.0
        self.assertFalse(wiz.action_apply_finished_lot())
        self.assertEqual(wiz.message_type, "error")
        self.assertFalse(self.production_tracked.lot_producing_ids)

    def test_22_finish_production_full_flow(self):
        """Scan components, apply finished lot, finish -> MO done."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        # Location barcode must never become a finished lot on a tracked MO
        self.assertFalse(wiz.finished_lot_id)
        self.assertFalse(wiz.finished_lot_name)
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        wiz.product_qty = 2.0
        self.assertTrue(wiz.action_confirm())
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.product_qty = 3.0
        self.assertTrue(wiz.action_confirm())
        # Apply the finished lot then finish the production
        wiz2 = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz2, "LOT-FIN-001")
        wiz2.finished_qty_producing = 1.0
        self.assertTrue(wiz2.action_apply_finished_lot())
        self.assertTrue(wiz2.action_finish_production())
        self.assertEqual(self.production_tracked.state, "done")

    def test_23_partial_production_returns_backorder_wizard(self):
        """Finishing with qty below demand returns the backorder wizard."""
        # Force create_backorder='ask' so the test is deterministic
        # regardless of the dev DB's picking type default.
        self.production.picking_type_id.create_backorder = "ask"
        # Consume components proportionally to the partial production
        # (core scales expected consumption by qty_producing / product_qty)
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 0.8, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        _, res = self._scan_component(
            self.production, self.component_simple, "PROD-COMP-S", 1.2,
        )
        self.assertTrue(res)
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "mrp.production.backorder")
        self.assertNotEqual(self.production.state, "done")

    def test_24_draft_mo_scan_rejected(self):
        """Scanning components / finishing is rejected on a draft MO."""
        draft_mo = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        wiz = self.WizScanMrp.create({"production_id": draft_mo.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.product_qty = 1.0
        res = wiz.action_confirm()
        self.assertFalse(res)
        self.assertEqual(wiz.message_type, "error")
        res = wiz.action_finish_production()
        self.assertFalse(res)
        self.assertEqual(draft_mo.state, "draft")

    def test_25_scan_non_internal_location_falls_through(self):
        """A non-internal location barcode is not treated as a location."""
        vendor_loc = self.StockLocation.create({
            "name": "Vendor Bin",
            "usage": "supplier",
            "barcode": "LOC-VENDOR-1",
        })
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Default location is pre-filled from the MO; the vendor barcode
        # must fall through (not_found) instead of replacing it.
        self.action_barcode_scanned(wiz, "LOC-VENDOR-1")
        self.assertEqual(wiz.location_id, self.components_location)
        self.assertNotEqual(wiz.location_id, vendor_loc)
        self.assertEqual(wiz.message_type, "not_found")

    def test_26_auto_consumes_unscaled_simple_partial(self):
        """Partial production auto-scales an unscanned non-tracked move.

        qty_producing 0.4, tracked component scanned proportionally (0.8),
        simple component not scanned at all. It must be auto-scaled to 1.2
        and picked, so the only remaining issue is the backorder wizard.
        """
        self.production.picking_type_id.create_backorder = "ask"
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 0.8, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        simple_move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        # Still reserved to the full demand before finishing
        self.assertEqual(simple_move.move_line_ids.quantity, 3.0)
        self.assertFalse(simple_move.picked)
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "mrp.production.backorder")
        # Simple component was auto-consumed at the scaled ratio (3 * 0.4)
        self.assertEqual(simple_move.move_line_ids.quantity, 1.2)
        self.assertTrue(simple_move.picked)
        self.assertTrue(simple_move.move_line_ids.picked)

    def test_27_auto_consumes_simple_full_production(self):
        """Full production: scanned tracked, unscanned simple auto-consumed.

        Mirrors enterprise 'Produce All': tracked components still need a
        lot scan, but non-tracked auto moves are consumed at full demand.
        """
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 2.0, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        simple_move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        self.assertFalse(simple_move.picked)
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        self.assertTrue(wiz.action_finish_production())
        self.assertEqual(self.production.state, "done")
        self.assertEqual(simple_move.move_line_ids.quantity, 3.0)
        self.assertTrue(simple_move.picked)

    def test_28_explicit_scanned_line_not_overwritten(self):
        """An explicit simple scan off-ratio is never auto-overwritten."""
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 0.8, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        _, res = self._scan_component(
            self.production, self.component_simple, "PROD-COMP-S", 1.5,
        )
        self.assertTrue(res)
        simple_move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        # Scanned 1.5 vs expected 1.2 -> consumption warning, value kept
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "mrp.consumption.warning")
        self.assertEqual(simple_move.move_line_ids.quantity, 1.5)
        self.assertTrue(simple_move.picked)

    def test_29_manual_consumption_move_not_scaled(self):
        """A manual_consumption move is excluded from auto-scaling."""
        _, res = self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 0.8, lot_barcode="LOT-COMP-001",
        )
        self.assertTrue(res)
        simple_move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        simple_move.manual_consumption = True
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        # Manual move kept at 3.0, not scaled to 1.2 -> consumption warning
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "mrp.consumption.warning")
        self.assertEqual(simple_move.move_line_ids.quantity, 3.0)

    def test_30_tracked_move_not_auto_consumed(self):
        """A tracked move is excluded even when reserved but not scanned."""
        _, res = self._scan_component(
            self.production, self.component_simple, "PROD-COMP-S", 1.2,
        )
        self.assertTrue(res)
        tracked_move = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_tracked
        )
        # Reserved line still at full demand with its lot
        self.assertEqual(tracked_move.move_line_ids.quantity, 2.0)
        self.assertEqual(tracked_move.move_line_ids.lot_id, self.component_lot)
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        # Tracked move not picked -> counts as 0 consumed vs expected 0.8
        self.assertIsInstance(res, dict)
        self.assertEqual(res.get("res_model"), "mrp.consumption.warning")
        self.assertEqual(tracked_move.move_line_ids.quantity, 2.0)
        self.assertEqual(tracked_move.move_line_ids.lot_id, self.component_lot)

    # --- TODO-A1: product fallback search ---

    def test_a1_branch1_jump_to_other_mo(self):
        """Scanning a component that belongs to another MO switches to it."""
        # Build a second MO with its own component
        comp_other = self.Product.create({
            "name": "Component Other MO",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-COMP-OTHER",
        })
        bom_other = self.MrpBom.create({
            "product_id": self.finished_product.id,
            "product_tmpl_id": self.finished_product.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": comp_other.id,
                "product_qty": 1.0,
                "product_uom_id": comp_other.uom_id.id,
            })],
        })
        mo_other = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": bom_other.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo_other.action_confirm()
        # Scan MO2's component from MO1's wizard
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "PROD-COMP-OTHER")
        # Switched to the other MO
        self.assertEqual(wiz.production_id, mo_other)
        self.assertEqual(wiz.message_type, "info")
        # Scan progress from MO1 is discarded
        self.assertFalse(wiz.product_id)

    def test_a1_branch2_prompt_force_add(self):
        """A product not in any MO BOM prompts to force-add (non-tracked)."""
        orphan = self.Product.create({
            "name": "Orphan Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-ORPHAN",
        })
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "PROD-ORPHAN")
        self.assertEqual(wiz.product_id, orphan)
        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_add)

    def test_a1_branch3_finished_product_error(self):
        """Scanning another MO's finished product is rejected by A1 branch 3.

        The current MO's own finished product is handled by A3 (auto-fill),
        so this test verifies the "any MO finished product -> error" path
        using a different MO's finished product.
        """
        other_finished = self.Product.create({
            "name": "Other Finished Product",
            "type": "consu",
            "is_storable": True,
            "barcode": "PROD-FIN-OTHER-A1",
        })
        other_bom = self.env["mrp.bom"].create({
            "product_tmpl_id": other_finished.product_tmpl_id.id,
            "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {
                "product_id": self.component_simple.id,
                "product_qty": 1.0,
            })],
        })
        other_mo = self.env["mrp.production"].create({
            "product_id": other_finished.id,
            "product_qty": 1.0,
            "bom_id": other_bom.id,
        })
        other_mo.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "PROD-FIN-OTHER-A1")
        self.assertEqual(wiz.message_type, "error")

    # --- TODO-A2: lot reverse lookup ---

    def test_a2_lookup_component_lot(self):
        """Scanning a lot of another tracked component switches product & binds lot."""
        # Add a second tracked component to the MO (raw material move)
        comp_b = self.Product.create({
            "name": "Component B Tracked",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-COMP-B",
        })
        lot_b = self.StockProductionLot.create({
            "name": "LOT-COMP-B-001",
            "product_id": comp_b.id,
            "company_id": self.company.id,
        })
        self.env["stock.move"].create({
            "product_id": comp_b.id,
            "product_uom_qty": 1.0,
            "product_uom": comp_b.uom_id.id,
            "raw_material_production_id": self.production.id,
            "location_id": self.components_location.id,
            "location_dest_id": comp_b.property_stock_production.id,
            "date": "2026-09-19 00:00:00",
            "company_id": self.company.id,
            "procure_method": "make_to_order",
        })
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        # Lock to the first tracked component
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.assertEqual(wiz.product_id, self.component_tracked)
        # Scan comp_b's lot -> reverse lookup switches product & binds lot
        self.action_barcode_scanned(wiz, "LOT-COMP-B-001")
        self.assertEqual(wiz.product_id, comp_b)
        self.assertEqual(wiz.lot_id, lot_b)
        self.assertEqual(wiz.lot_name, "LOT-COMP-B-001")

    def test_a2_lookup_failure_errors(self):
        """Scanning a lot of an unrelated product errors, no new lot bound."""
        unrelated = self.Product.create({
            "name": "Unrelated Tracked Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-UNRELATED",
        })
        lot_unrelated = self.StockProductionLot.create({
            "name": "LOT-UNRELATED-001",
            "product_id": unrelated.id,
            "company_id": self.company.id,
        })
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.action_barcode_scanned(wiz, "LOT-UNRELATED-001")
        self.assertEqual(wiz.message_type, "error")
        # No lot bound to the wizard (not treated as a new lot)
        self.assertFalse(wiz.lot_id)
        # The unrelated lot is untouched in the DB
        self.assertTrue(lot_unrelated.exists())

    # --- TODO-A3: auto-fill components from finished product scan ---

    def test_a3_auto_fill_all_available(self):
        """Scanning finished product fills all components to demand."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # finished_qty_producing defaults to 1.0 < product_qty 2.0, so
        # demand <= reserved -> every component is fully filled.
        self.action_barcode_scanned(wiz, "PROD-FIN-A")
        self.assertEqual(wiz.message_type, "info")
        for move in self.production.move_raw_ids:
            self.assertTrue(move.picked)
            demand = move.product_uom.round(
                move.unit_factor * (wiz.finished_qty_producing or self.production.product_qty)
            )
            consumed = sum(move.move_line_ids.mapped("quantity"))
            self.assertAlmostEqual(consumed, demand, places=4)

    def test_a3_auto_fill_partial(self):
        """When demand exceeds on-hand stock, only the available qty is consumed."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Demand far exceeds the 100 units in stock -> only available qty filled.
        wiz.finished_qty_producing = 200.0
        self.action_barcode_scanned(wiz, "PROD-FIN-A")
        for move in self.production.move_raw_ids:
            self.assertTrue(move.picked)
            consumed = sum(move.move_line_ids.mapped("quantity"))
            demand = move.product_uom.round(move.unit_factor * wiz.finished_qty_producing)
            # Only the available stock was consumed (demand > on-hand).
            self.assertLess(consumed, demand)

    def test_a4_unreserved_component_auto_consumed_at_finish(self):
        """Zero-reservation non-tracked components are auto-consumed at finish.

        Regression: _auto_fill_components() marked unreserved raw moves as
        picked without filling any quantity; _auto_consume_non_tracked_
        components() then skipped them (not picked filter), so the component
        was consumed as 0 and the raw move was cancelled after the operator
        confirmed the Consumption Warning. Now finish returns True directly,
        the component is consumed at full demand and the finished SN lands
        on the finished move line.
        """
        comp = self.Product.create({
            "name": "Unreserved Component",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-COMP-UNRES",
        })
        # Stock exists, but the MO is explicitly unreserved: the raw move
        # has stock to draw from yet zero reservation move lines, which is
        # the state that triggered the picked/qty=0 deadlock.
        self.StockQuant.create({
            "product_id": comp.id,
            "location_id": self.components_location.id,
            "quantity": 1.0,
        })
        finished = self.Product.create({
            "name": "Serial Finished A4",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-FIN-SER-A4",
        })
        sn = self.StockProductionLot.create({
            "name": "SN-A4-001",
            "product_id": finished.id,
            "company_id": self.company.id,
        })
        bom = self.MrpBom.create({
            "product_id": finished.id,
            "product_tmpl_id": finished.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": comp.id,
                "product_qty": 1.0,
                "product_uom_id": comp.uom_id.id,
            })],
        })
        mo = self.MrpProduction.create({
            "product_id": finished.id,
            "product_qty": 1.0,
            "bom_id": bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo.action_confirm()
        raw = mo.move_raw_ids
        raw._do_unreserve()
        self.assertFalse(sum(raw.move_line_ids.mapped("quantity")))

        wiz = self.WizScanMrp.create({"production_id": mo.id})
        self.action_barcode_scanned(wiz, "SN-A4-001")
        self.assertEqual(wiz.finished_lot_id, sn)
        # Unreserved moves must NOT be marked picked at scan time.
        self.assertFalse(raw.picked)

        res = wiz.action_finish_production()
        self.assertIs(res, True)  # no Consumption Warning wizard
        self.assertEqual(mo.state, "done")
        self.assertEqual(raw.state, "done")
        self.assertAlmostEqual(raw.quantity, 1.0, places=4)
        self.assertEqual(mo.lot_producing_ids, sn)
        self.assertEqual(mo.move_finished_ids.move_line_ids.lot_id, sn)

    def test_a3_finished_barcode_other_mo_falls_to_a1(self):
        """Scanning another MO's finished product falls through to A1 (error)."""
        other_finished = self.Product.create({
            "name": "Other Finished Product",
            "type": "consu",
            "is_storable": True,
            "barcode": "PROD-FIN-OTHER",
        })
        other_bom = self.env["mrp.bom"].create({
            "product_tmpl_id": other_finished.product_tmpl_id.id,
            "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {
                "product_id": self.component_simple.id,
                "product_qty": 1.0,
            })],
        })
        other_mo = self.env["mrp.production"].create({
            "product_id": other_finished.id,
            "product_qty": 1.0,
            "bom_id": other_bom.id,
        })
        other_mo.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "PROD-FIN-OTHER")
        self.assertEqual(wiz.message_type, "error")

    # --- TODO-B1: work-order queue ---

    def _make_mo_with_workcenter(self, workcenter):
        """Create a confirmed MO and attach a workorder on `workcenter`."""
        mo = self.env["mrp.production"].create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
        })
        mo.action_confirm()
        self.env["mrp.workorder"].create({
            "name": "Op",
            "production_id": mo.id,
            "workcenter_id": workcenter.id,
        })
        return mo

    def test_b1_queue_loads(self):
        """Default My Work Orders mode loads MOs on the user's workcenters."""
        wc = self.env["mrp.workcenter"].create({"name": "WC"})
        self.env.user.mrp_workcenter_ids = [(6, 0, [wc.id])]
        mo = self._make_mo_with_workcenter(wc)
        wiz = self.WizScanMrp.create({})
        self.assertEqual(wiz.queue_mode, "my")
        self.assertIn(mo, wiz.queue_workorders_ids)

    def test_b1_queue_my_filter(self):
        """My Work Orders excludes MOs on workcenters not assigned to user."""
        wc1 = self.env["mrp.workcenter"].create({"name": "WC1"})
        wc2 = self.env["mrp.workcenter"].create({"name": "WC2"})
        self.env.user.mrp_workcenter_ids = [(6, 0, [wc1.id])]
        mo1 = self._make_mo_with_workcenter(wc1)
        mo2 = self._make_mo_with_workcenter(wc2)
        wiz = self.WizScanMrp.create({})
        self.assertIn(mo1, wiz.queue_workorders_ids)
        self.assertNotIn(mo2, wiz.queue_workorders_ids)

    def test_b1_queue_all_mode(self):
        """All MO mode includes every confirmed/progress MO (e.g. base MO)."""
        wiz = self.WizScanMrp.create({})
        wiz.queue_mode = "all"
        self.assertIn(self.production, wiz.queue_workorders_ids)

    def test_b1_queue_filters(self):
        """High-priority filter shows only priority >= 2 MOs."""
        mo_high = self.env["mrp.production"].create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "priority": "1",
        })
        mo_high.action_confirm()
        wiz = self.WizScanMrp.create({})
        wiz.queue_mode = "all"
        wiz.queue_filter_priority = True
        self.assertIn(mo_high, wiz.queue_workorders_ids)
        self.assertNotIn(self.production, wiz.queue_workorders_ids)

    # --- TODO-B2: scan-first MO switching ---

    def test_b2_scan_mo_barcode_switches(self):
        """Scanning an MO reference switches directly; own MO is a no-op;
        an unknown barcode falls through to not_found."""
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        self.assertNotEqual(mo2.name, "New")
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Scan MO2's reference -> direct switch, no confirmation
        self.action_barcode_scanned(wiz, mo2.name)
        self.assertEqual(wiz.production_id, mo2)
        self.assertEqual(wiz.message_type, "info")
        # Scanning the current MO's own reference does not switch
        self.action_barcode_scanned(wiz, mo2.name)
        self.assertEqual(wiz.production_id, mo2)
        # Unknown barcode is not swallowed by the MO scanner
        self.action_barcode_scanned(wiz, "NO-SUCH-MO-000999")
        self.assertEqual(wiz.production_id, mo2)
        self.assertEqual(wiz.message_type, "not_found")

    def test_b2_scan_other_mo_component_switches(self):
        """Scanning a component exclusive to another MO switches to it and
        stashes the current uncommitted scan progress."""
        comp_b2 = self.Product.create({
            "name": "Component B2 Only",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-COMP-B2",
        })
        bom2 = self.MrpBom.create({
            "product_id": self.finished_product.id,
            "product_tmpl_id": self.finished_product.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": comp_b2.id,
                "product_qty": 1.0,
                "product_uom_id": comp_b2.uom_id.id,
            })],
        })
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": bom2.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Build uncommitted scan progress on MO1 (component scanned,
        # quantity not yet confirmed).
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        self.assertEqual(wiz.product_id, self.component_simple)
        # Scan MO2-exclusive component -> switch directly
        self.action_barcode_scanned(wiz, "PROD-COMP-B2")
        self.assertEqual(wiz.production_id, mo2)
        self.assertEqual(wiz.message_type, "info")
        # MO1 progress is discarded from the screen...
        self.assertFalse(wiz.product_id)
        # ...but stashed per MO (restored in TODO-B3)
        stash = wiz.scan_progress_stash or {}
        self.assertIn(str(self.production.id), stash)
        self.assertEqual(
            stash[str(self.production.id)]["product_id"],
            self.component_simple.id,
        )

    def test_b2_ambiguous_component_shows_selector(self):
        """A component belonging to several MOs shows the selection list;
        picking a candidate switches and clears the selector."""
        shared = self.Product.create({
            "name": "Component Shared B2",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-SHARED-B2",
        })
        bom_shared = self.MrpBom.create({
            "product_id": self.finished_product.id,
            "product_tmpl_id": self.finished_product.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": shared.id,
                "product_qty": 1.0,
                "product_uom_id": shared.uom_id.id,
            })],
        })
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": bom_shared.id,
        })
        mo2.action_confirm()
        mo3 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": bom_shared.id,
        })
        mo3.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "PROD-SHARED-B2")
        # Ambiguous -> selector with both candidates
        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_switch_selector)
        self.assertEqual(
            set(wiz.pending_switch_production_ids.ids),
            {mo2.id, mo3.id},
        )
        self.assertEqual(wiz.production_id, self.production)
        # Pick MO2 via the list button (wizard id passed explicitly,
        # NOT active_id).
        mo2.with_context(barcode_wizard_id=wiz.id).action_switch_to_in_barcode()
        self.assertEqual(wiz.production_id, mo2)
        # Selector is cleared after switching
        self.assertFalse(wiz.visible_switch_selector)
        self.assertFalse(wiz.pending_switch_production_ids)

    def test_b2_switched_context_correct(self):
        """After switching, all wizard context reflects the new MO."""
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Leave some stale scan state before switching
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        self.action_barcode_scanned(wiz, mo2.name)
        # MO context
        self.assertEqual(wiz.production_id, mo2)
        self.assertEqual(wiz.res_id, mo2.id)
        self.assertEqual(
            wiz.res_model_id, self.env.ref("mrp.model_mrp_production")
        )
        # Locations / quantities re-derived from MO2
        self.assertEqual(wiz.location_id, mo2.location_src_id)
        self.assertEqual(wiz.finished_qty_producing, mo2.product_qty)
        # Finished product is not tracked -> step starts at 1
        self.assertEqual(wiz.step, 1)
        # All previous scan state cleared
        self.assertFalse(wiz.workorder_id)
        self.assertFalse(wiz.product_id)
        self.assertFalse(wiz.lot_id)
        self.assertFalse(wiz.finished_lot_id)
        self.assertFalse(wiz.visible_force_add)
        self.assertFalse(wiz.visible_force_done)

    # --- TODO-B2: onchange contract regression (browser-path crash) ---
    # The barcode_events_mixin._on_barcode_scanned transparently returns
    # on_barcode_scanned's return value to the ORM onchange framework
    # (orm/models.py _apply_onchange_methods ~L6996-6998):
    #     if not res: continue
    #     if res.get('value'): ...
    # A bool True from on_barcode_scanned therefore reaches `True.get`
    # and crashes the web client with AttributeError. on_barcode_scanned
    # MUST return None (or a dict). The existing B2 unit tests use the
    # action_barcode_scanned helper which calls _on_barcode_scanned()
    # without inspecting the return value, so they passed while the
    # browser crashed. These two cases assert the contract directly and
    # through the onchange RPC surface the browser uses.

    def test_b2_on_barcode_scanned_returns_none_not_bool(self):
        """on_barcode_scanned must not return a truthy non-dict value.

        _on_barcode_scanned in the mixin returns whatever we return here
        to ORM onchange, which does `res.get('value')` on it. A True
        return therefore raises AttributeError in the browser.
        """
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        wiz._barcode_scanned = "LOC-COMP-001"
        res = wiz._on_barcode_scanned()
        self.assertFalse(
            res,
            msg="_on_barcode_scanned must return None/empty for the ORM "
                "onchange contract, got %r" % (res,),
        )
        wiz._barcode_scanned = "PROD-COMP-S"
        res = wiz._on_barcode_scanned()
        self.assertFalse(
            res and not isinstance(res, dict),
            msg="on_barcode_scanned must return None/dict, got %r" % (res,),
        )

    def test_b2_onchange_browser_path_does_not_crash(self):
        """Simulate the web client onchange RPC: model.onchange(values,
        field_names, fields_spec). Regression for the browser-side
        AttributeError that the direct-call unit tests missed.

        NB: fields_spec mirrors the format the web client sends — a
        dict[str, dict] where each value is a (possibly empty) sub-spec.
        Passing field objects instead raises TypeError in web_read
        (`'fields' not in field_spec`), masking the real bug.
        """
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        field_names = ["_barcode_scanned"]
        field_names_all = [
            "_barcode_scanned", "barcode", "production_id",
            "finished_lot_id", "product_id", "lot_id", "location_id",
            "step", "message", "message_type",
        ]
        fields_spec = {name: {} for name in field_names_all}
        values = {
            "production_id": self.production.id,
            "_barcode_scanned": "LOC-COMP-001",
        }
        result = self.WizScanMrp.with_context(__onchange=True).onchange(
            values, field_names, fields_spec,
        )
        self.assertIsInstance(
            result, dict,
            msg="onchange must return a dict, got %r" % (result,),
        )
        # Second scan in the same RPC batch — exercises the second step
        # of the flow (component product) where the bool return was
        # previously True and crashed the ORM.
        values = dict(result.get("value", {}))
        values["_barcode_scanned"] = "PROD-COMP-S"
        result = self.WizScanMrp.with_context(__onchange=True).onchange(
            values, ["_barcode_scanned"], fields_spec,
        )
        self.assertIsInstance(
            result, dict,
            msg="onchange second scan must return a dict, got %r" % (result,),
        )

    # --- TODO-B3: queued progress restore ---

    def test_b3_restore_component_progress(self):
        """Switching away and back restores the half-scanned component line
        (product / lot / qty / location / step) and consumes the stash."""
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Half-scanned component line (not confirmed)
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        wiz.product_qty = 2.0
        self.assertEqual(wiz.step, 4)
        # Switch away -> stashed, screen cleared
        self.action_barcode_scanned(wiz, mo2.name)
        self.assertEqual(wiz.production_id, mo2)
        self.assertFalse(wiz.product_id)
        self.assertIn(str(self.production.id), wiz.scan_progress_stash)
        # Switch back -> state identical to when we left
        self.action_barcode_scanned(wiz, self.production.name)
        self.assertEqual(wiz.production_id, self.production)
        self.assertEqual(wiz.product_id, self.component_tracked)
        self.assertEqual(wiz.product_uom_id, self.component_tracked.uom_id)
        self.assertEqual(wiz.lot_id, self.component_lot)
        self.assertEqual(wiz.lot_name, "LOT-COMP-001")
        self.assertEqual(wiz.product_qty, 2.0)
        self.assertEqual(wiz.location_id, self.components_location)
        self.assertEqual(wiz.step, 4)
        # Stash entry consumed by the restore
        self.assertNotIn(str(self.production.id), wiz.scan_progress_stash or {})

    def test_b3_restore_finished_lot_and_default_fallback(self):
        """Finished-lot progress on a tracked MO is restored; arriving at an
        MO that never had a stash falls back to plain defaults."""
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        mo3 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 5.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo3.action_confirm()
        wiz = self.WizScanMrp.create(
            {"production_id": self.production_tracked.id}
        )
        # Step 0: finished lot scanned, custom qty, not applied yet
        self.assertEqual(wiz.step, 0)
        wiz.finished_lot_id = self.finished_lot
        wiz.finished_lot_name = self.finished_lot.name
        wiz.finished_qty_producing = 3.0
        # Switch to MO2 (untracked finished) -> stash + fresh defaults
        self.action_barcode_scanned(wiz, mo2.name)
        self.assertEqual(wiz.production_id, mo2)
        self.assertFalse(wiz.finished_lot_id)
        self.assertEqual(wiz.step, 1)
        # Back to the tracked MO -> finished lot state restored
        self.action_barcode_scanned(wiz, self.production_tracked.name)
        self.assertEqual(wiz.finished_lot_id, self.finished_lot)
        self.assertEqual(wiz.finished_lot_name, "LOT-FIN-001")
        self.assertEqual(wiz.finished_qty_producing, 3.0)
        self.assertEqual(wiz.step, 0)
        self.assertNotIn(
            str(self.production_tracked.id), wiz.scan_progress_stash or {}
        )
        # Arrive at MO3, which never had any stash -> plain defaults,
        # not the restored values from another MO.
        self.action_barcode_scanned(wiz, mo3.name)
        self.assertEqual(wiz.production_id, mo3)
        self.assertFalse(wiz.finished_lot_id)
        self.assertFalse(wiz.finished_lot_name)
        self.assertEqual(wiz.finished_qty_producing, 5.0)
        self.assertEqual(wiz.location_id, mo3.location_src_id)
        self.assertEqual(wiz.step, 1)

    # --- TODO-C1/C2: step indicator + dynamic guidance ---

    def test_c2_guided_flow_step_messages(self):
        """Tracked-MO flow: the banner instruction follows step + context
        (finished product at step 0, MO/location at 1, component at 3/4)."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        self.assertIn("finished product lot", wiz.message)
        self.assertIn(self.finished_product_tracked.name, wiz.message)
        # Scan finished lot -> step 2 (auto-fill runs, lot bound on wizard)
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        self.assertEqual(wiz.finished_lot_id, self.finished_lot)
        self.assertEqual(wiz.step, 2)
        # Apply -> step 1, banner names the MO and the source location
        wiz.action_apply_finished_lot()
        self.assertEqual(wiz.step, 1)
        self.assertIn(self.production_tracked.name, wiz.message)
        self.assertIn(self.components_location.name, wiz.message)
        # Location scanned -> step 2
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertEqual(wiz.step, 2)
        self.assertIn("component", wiz.message)
        self.assertIn(self.production_tracked.name, wiz.message)
        # Tracked component -> step 3 names the component
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.assertEqual(wiz.step, 3)
        self.assertIn("lot/serial", wiz.message)
        self.assertIn(self.component_tracked.name, wiz.message)
        # Lot scanned -> step 4 asks for the quantity
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        self.assertEqual(wiz.step, 4)
        self.assertIn("quantity", wiz.message)
        self.assertIn(self.component_tracked.name, wiz.message)

    def test_c2_untracked_shortcut_messages(self):
        """Untracked finished MO starts at step 1; untracked components jump
        straight to the quantity step; confirming returns to step 2."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.assertEqual(wiz.step, 1)
        self.assertIn(self.production.name, wiz.message)
        self.assertIn(self.components_location.name, wiz.message)
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertEqual(wiz.step, 2)
        self.assertIn("component", wiz.message)
        # Untracked component: no lot step, straight to quantity
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        self.assertEqual(wiz.step, 4)
        self.assertIn("quantity", wiz.message)
        self.assertIn(self.component_simple.name, wiz.message)
        # Confirm -> back to expecting the next component (step 2)
        wiz.action_confirm()
        self.assertEqual(wiz.step, 2)
        self.assertIn("component", wiz.message)

    def test_c2_restore_step_message(self):
        """After a switch away/back, the banner shows the restored step's
        dynamic instruction (B3 restore + C2 messaging combined)."""
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Drive to step 3 (component scanned, lot pending)
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.assertEqual(wiz.step, 3)
        # Switch away and back
        self.action_barcode_scanned(wiz, mo2.name)
        self.assertEqual(wiz.production_id, mo2)
        self.action_barcode_scanned(wiz, self.production.name)
        self.assertEqual(wiz.production_id, self.production)
        # Restored step 3 with its dynamic instruction
        self.assertEqual(wiz.step, 3)
        self.assertIn("lot/serial", wiz.message)
        self.assertIn(self.component_tracked.name, wiz.message)
        self.assertNotIn(
            str(self.production.id), wiz.scan_progress_stash or {}
        )

    # --- TODO-C4: component checklist ---

    def test_c4_checklist_data(self):
        """Component checklist shows all MO raw moves with correct data."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        moves = wiz.component_move_ids
        self.assertEqual(len(moves), 2)
        products = moves.mapped("product_id")
        self.assertIn(self.component_tracked, products)
        self.assertIn(self.component_simple, products)
        # Initial state: no moves picked
        self.assertFalse(any(m.picked for m in moves))

    def test_c4_checklist_after_auto_fill(self):
        """After scanning finished product, checklist reflects picked status."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Initial: all not picked
        self.assertFalse(any(m.picked for m in wiz.component_move_ids))
        # Scan finished product -> auto-fill picks all stocked components
        self.action_barcode_scanned(wiz, "PROD-FIN-A")
        # Both components have stock -> both picked
        self.assertTrue(all(m.picked for m in wiz.component_move_ids))

    def test_c4_checklist_single_component_scan(self):
        """Checklist picked status after scanning components one by one."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Scan location then component, then confirm
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-S")
        wiz.action_confirm()
        # Check if move.picked reflects the manual scan
        simple_move = wiz.component_move_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        self.assertTrue(simple_move, "Component simple move not found")
        self.assertTrue(
            simple_move.picked,
            "move.picked is False after manual scan + confirm; "
            "_process_stock_move_line only sets move_line.picked",
        )

    # --- TODO-D3: dialog-close banner refresh ---

    def test_d3_onchange_sets_done_banner(self):
        """After a dialog-close reload, production_state=done + the
        pending_finish flag flips the placeholder info banner into a
        real 'Production done' success banner; the flag is consumed."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # Simulate the dialog path: action_finish_production returned a
        # dialog action and stashed the flag with an info placeholder.
        wiz.pending_finish = True
        wiz._set_message(
            "info",
            "Resolving consumption warning for %s..." % self.production.name,
        )
        # Simulate the MO becoming done after the dialog closed.
        self.production.state = "done"
        # Trigger the onchange (client does this on reload when a tracked
        # field changes).
        wiz._onchange_production_state()
        self.assertEqual(wiz.message_type, "success")
        self.assertIn("Production done", wiz.message)
        self.assertIn(self.production.name, wiz.message)
        # Flag consumed so a later unrelated state change does not
        # re-trigger the success banner.
        self.assertFalse(wiz.pending_finish)

    def test_d3_onchange_noop_without_pending_flag(self):
        """Without the pending_finish flag, _onchange_production_state
        leaves the banner alone — even if the MO went done. This prevents
        the banner from being clobbered when the user picks an
        already-done MO from the queue."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        # No pending_finish flag set; banner has the normal step message.
        original_message = wiz.message
        self.production.state = "done"
        wiz._onchange_production_state()
        self.assertEqual(wiz.message, original_message)
        self.assertNotEqual(wiz.message_type, "success")

    def test_d3_onchange_keeps_banner_if_still_progress(self):
        """If the dialog closed but the MO is still progress (user
        cancelled the consumption warning), the placeholder banner stays
        and the flag stays set so a later reload can still flip it."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        wiz.pending_finish = True
        wiz._set_message(
            "info",
            "Resolving consumption warning for %s..." % self.production.name,
        )
        placeholder = wiz.message
        # MO stays progress (dialog cancelled, no mark done happened).
        self.production.state = "progress"
        wiz._onchange_production_state()
        # Banner unchanged; flag stays set for a later reload to consume.
        self.assertEqual(wiz.message, placeholder)
        self.assertTrue(wiz.pending_finish)

    # --- TODO-C5: scan-first MO switching from MO list ---

    def test_scan_first_product_single_match(self):
        """Scan-first: scanning a product barcode lands on the unique
        active MO producing that product and auto-fills components."""
        # Fresh product with exactly one active MO (avoids cls.production
        # also matching the same finished_product barcode).
        single_product = self.Product.create({
            "name": "Single Match Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-SINGLE-MATCH",
        })
        single_bom = self.MrpBom.create({
            "product_id": single_product.id,
            "product_tmpl_id": single_product.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": self.component_simple.id,
                "product_qty": 1.0,
                "product_uom_id": self.component_simple.uom_id.id,
            })],
        })
        single_mo = self.MrpProduction.create({
            "product_id": single_product.id,
            "product_qty": 1.0,
            "bom_id": single_bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        single_mo.action_confirm()
        # Reserve stock so _auto_fill_components has move lines to scale.
        single_mo.action_assign()
        # Wizard with no MO starting point (scan-first mode)
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "PROD-SINGLE-MATCH")
        # Single active MO -> switch directly + auto-fill
        self.assertEqual(wiz.production_id, single_mo)
        self.assertEqual(wiz.message_type, "info")
        move = single_mo.move_raw_ids.filtered(
            lambda m: m.product_id == self.component_simple
        )
        self.assertTrue(move.picked)

    def test_scan_first_product_multi_match_sets_flag(self):
        """Scan-first: ambiguous product barcode (multiple active MOs)
        sets the selector flag — operator must click 'View candidate MOs'
        button to open the filtered list (onchange cannot return action)."""
        # cls.production + a second MO both producing finished_product
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "PROD-FIN-A")
        # Ambiguous -> flag set, button visible, no auto-switch
        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_switch_selector)
        self.assertEqual(
            set(wiz.pending_switch_production_ids.ids),
            {self.production.id, mo2.id},
        )
        self.assertFalse(wiz.production_id)

    def test_scan_first_product_no_active_mo_errors(self):
        """Scan-first: a product barcode with no active MO producing it
        errors (operator should be told the MO is missing/inactive)."""
        orphan_product = self.Product.create({
            "name": "Orphan Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-ORPHAN",
        })
        # No MO created for orphan_product
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "PROD-ORPHAN")
        self.assertEqual(wiz.message_type, "error")
        self.assertFalse(wiz.production_id)

    def test_scan_first_sn_single_match(self):
        """Scan-first: scanning a SN pre-assigned to a MO's
        lot_producing_ids switches to that MO and binds finished_lot_id."""
        sn = self.StockProductionLot.create({
            "name": "SN-PREASSIGN-001",
            "product_id": self.finished_product_tracked.id,
            "company_id": self.company.id,
        })
        mo_with_sn = self.MrpProduction.create({
            "product_id": self.finished_product_tracked.id,
            "product_qty": 1.0,
            "bom_id": self.bom_tracked.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo_with_sn.action_confirm()
        # Pre-assign the SN to the MO (user-confirmed: SN lives in
        # lot_producing_ids, NOT in a generic product search).
        mo_with_sn.lot_producing_ids = [(6, 0, [sn.id])]
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "SN-PREASSIGN-001")
        # SN -> MO single match -> switch + bind finished_lot_id
        self.assertEqual(wiz.production_id, mo_with_sn)
        self.assertEqual(wiz.finished_lot_id, sn)
        self.assertEqual(wiz.message_type, "info")

    def test_scan_first_sn_multi_match_sets_flag(self):
        """Scan-first: a SN assigned to multiple active MOs sets the
        selector flag (same flag as the product multi-match path)."""
        shared_sn = self.StockProductionLot.create({
            "name": "SN-SHARED-MULTI",
            "product_id": self.finished_product_tracked.id,
            "company_id": self.company.id,
        })
        mo_a = self.MrpProduction.create({
            "product_id": self.finished_product_tracked.id,
            "product_qty": 1.0,
            "bom_id": self.bom_tracked.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo_a.action_confirm()
        mo_b = self.MrpProduction.create({
            "product_id": self.finished_product_tracked.id,
            "product_qty": 1.0,
            "bom_id": self.bom_tracked.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo_b.action_confirm()
        # Same SN pre-assigned to both MOs (lot_producing_ids is M2m,
        # so a lot can technically be linked to several MOs).
        mo_a.lot_producing_ids = [(6, 0, [shared_sn.id])]
        mo_b.lot_producing_ids = [(6, 0, [shared_sn.id])]
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "SN-SHARED-MULTI")
        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_switch_selector)
        self.assertEqual(
            set(wiz.pending_switch_production_ids.ids),
            {mo_a.id, mo_b.id},
        )
        self.assertFalse(wiz.production_id)
        # finished_lot_id not bound yet — must wait for operator pick
        self.assertFalse(wiz.finished_lot_id)

    def test_scan_first_sn_done_mo_message(self):
        """Scan-first: a SN whose only MO is already done shows a
        friendly 'MO already done' message, no switch."""
        done_sn = self.StockProductionLot.create({
            "name": "SN-DONE-001",
            "product_id": self.finished_product_tracked.id,
            "company_id": self.company.id,
        })
        done_mo = self.MrpProduction.create({
            "product_id": self.finished_product_tracked.id,
            "product_qty": 1.0,
            "bom_id": self.bom_tracked.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        done_mo.action_confirm()
        done_mo.lot_producing_ids = [(6, 0, [done_sn.id])]
        # Mark MO done (state=done) — bypass the full finish flow
        done_mo.state = "done"
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "SN-DONE-001")
        self.assertEqual(wiz.message_type, "info")
        self.assertIn("already done", wiz.message.lower())
        self.assertFalse(wiz.production_id)

    def test_scan_first_sn_unassigned_falls_through(self):
        """Scan-first: a SN that exists but is not assigned to any MO
        (e.g. a component lot consumed elsewhere) makes
        _scan_finished_lot_reverse return False — does NOT raise an
        'unbound SN' error. Downstream scanners then handle it (or
        report not_found, which is acceptable)."""
        # cls.component_lot is a component lot (LOT-COMP-001), not in
        # any MO's lot_producing_ids.
        wiz = self.WizScanMrp.create({})
        # Direct call to the new method — must return False, NOT set
        # an 'unbound SN' error message on the wizard.
        res = wiz._scan_finished_lot_reverse("LOT-COMP-001")
        self.assertFalse(res)
        self.assertFalse(wiz.production_id, "Unassigned SN must not switch MO")
        self.assertFalse(wiz.finished_lot_id, "Unassigned SN must not bind finished_lot_id")

    def test_action_open_candidate_list_returns_act_window(self):
        """Button method (not onchange) returns a target='current'
        act_window for the filtered list — onchange cannot return an
        action, so the operator clicks this button after a multi-match
        scan sets the flag."""
        mo1 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo1.action_confirm()
        mo2 = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "bom_id": self.bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo2.action_confirm()
        wiz = self.WizScanMrp.create({})
        self.action_barcode_scanned(wiz, "PROD-FIN-A")
        # Flag is set
        self.assertTrue(wiz.visible_switch_selector)
        candidate_ids = set(wiz.pending_switch_production_ids.ids)
        # Button method (type=object, not onchange) returns an action
        action = wiz.action_open_candidate_list()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], "mrp.production")
        self.assertEqual(action["view_mode"], "list")
        self.assertEqual(action["target"], "current")
        # Domain restricts to the candidate MOs. The "in" operator
        # carries the ids as a list-valued third tuple element.
        domain_ids = set()
        for d in action["domain"]:
            if d[0] == "id" and d[1] == "in":
                domain_ids.update(d[2])
        self.assertEqual(domain_ids, candidate_ids)
        # barcode_wizard_id passed so row buttons can switch the wizard
        self.assertEqual(action.get("context", {}).get("barcode_wizard_id"), wiz.id)

    # --- Task 1: scan new finished SN → pending lot name (two-phase) ---

    def test_t1_scan_new_sn_after_product_creates_pending_lot(self):
        """After auto-fill, a new SN is recorded as pending finished lot
        name only — no stock.lot and no lot_producing_ids at scan time."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        # Scan finished product barcode → auto-fill, step 2
        self.action_barcode_scanned(wiz, "PROD-FIN-T")
        self.assertEqual(wiz.step, 2)
        self.assertFalse(wiz.finished_lot_id)
        # Scan a brand-new SN
        self.action_barcode_scanned(wiz, "NEW-FIN-999")
        self.assertEqual(wiz.finished_lot_name, "NEW-FIN-999")
        self.assertFalse(wiz.finished_lot_id)  # two-phase: lot not created yet
        self.assertEqual(wiz.step, 2)
        self.assertEqual(wiz.message_type, "info")
        self.assertIn("NEW-FIN-999", wiz.message)
        # No stock.lot exists, MO is untouched
        self.assertFalse(self.StockProductionLot.search([
            ("name", "=", "NEW-FIN-999"),
        ]))
        self.assertFalse(self.production_tracked.lot_producing_ids)

    def test_t1_scan_new_sn_at_step_0_directly(self):
        """Scan a new SN directly (skip product barcode): pending name is
        recorded and components are still auto-filled (idempotent)."""
        self.production_tracked.action_assign()
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        self.action_barcode_scanned(wiz, "BRAND-NEW-SN-001")
        self.assertFalse(wiz.finished_lot_id)
        self.assertEqual(wiz.finished_lot_name, "BRAND-NEW-SN-001")
        self.assertEqual(wiz.step, 2)
        self.assertIn("BRAND-NEW-SN-001", wiz.message)
        # _auto_fill_components ran: reserved raw moves are marked picked
        for move in self.production_tracked.move_raw_ids:
            self.assertTrue(
                move.picked,
                "Raw move %s should be picked after auto-fill" % move.product_id.name,
            )

    def test_t1_scan_existing_lot_at_step_2_does_not_reset_step(self):
        """At step 2, scanning an existing finished lot keeps step=2."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        # Scan product barcode → auto-fill → step 2
        self.action_barcode_scanned(wiz, "PROD-FIN-T")
        self.assertEqual(wiz.step, 2)
        # Now scan existing finished lot
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        self.assertEqual(wiz.finished_lot_id, self.finished_lot)
        self.assertEqual(wiz.step, 2)

    def test_t1_product_barcode_not_treated_as_pending_lot(self):
        """Product barcode must not be swallowed as a pending finished lot."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        # Scan finished product barcode → _scan_product path, not pending lot
        self.action_barcode_scanned(wiz, "PROD-FIN-T")
        self.assertFalse(wiz.finished_lot_id)
        self.assertNotEqual(wiz.finished_lot_name, "PROD-FIN-T")
        self.assertEqual(wiz.step, 2)
        self.assertIn("auto-filled", wiz.message)

    def test_t1_scan_new_sn_then_apply_writes_lot_producing_ids(self):
        """Pending SN → action_apply_finished_lot creates the lot and
        writes lot_producing_ids on the MO (second phase)."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, "FINAL-SN-42")
        # Scan phase: pending name only
        self.assertFalse(wiz.finished_lot_id)
        self.assertEqual(wiz.finished_lot_name, "FINAL-SN-42")
        # Apply → lot created and written to MO
        wiz.finished_qty_producing = 1.0
        res = wiz.action_apply_finished_lot()
        self.assertTrue(res)
        lot = self.StockProductionLot.search([
            ("name", "=", "FINAL-SN-42"),
            ("product_id", "=", self.finished_product_tracked.id),
        ])
        self.assertTrue(lot)
        self.assertIn(lot.id, self.production_tracked.lot_producing_ids.ids)
        self.assertEqual(lot.product_id, self.finished_product_tracked)
        self.assertEqual(self.production_tracked.qty_producing, 1.0)

    def test_t1_location_barcode_not_treated_as_pending_lot(self):
        """On a tracked MO, a location barcode is handled by _scan_location
        and never recorded as a pending finished lot name."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.assertEqual(wiz.step, 0)
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.assertFalse(wiz.finished_lot_id)
        self.assertFalse(wiz.finished_lot_name)
        self.assertEqual(wiz.location_id, self.components_location)
        self.assertEqual(wiz.step, 2)
        self.assertEqual(wiz.message_type, "info")

    # --- Task 3: auto-switch to next MO after finish ---

    def test_t3_finish_auto_switches_to_next_mo(self):
        """Finishing an MO auto-switches the wizard to another confirmed MO
        in the queue (queue_mode='all' to bypass workcenter filtering)."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.queue_mode = "all"
        # self.production is untracked → no finished lot needed.
        res = wiz.action_finish_production()
        self.assertTrue(res)
        # The wizard must have jumped to a different confirmed MO.
        self.assertNotEqual(wiz.production_id, self.production)
        self.assertIn("Switched to", wiz.message)
        self.assertEqual(wiz.message_type, "success")
        # Original MO is done.
        self.assertEqual(self.production.state, "done")

    def test_t3_finish_no_next_mo_stays(self):
        """When no MO remains in the queue, finish keeps the wizard on the
        done MO with a 'No more MOs' success message.

        Uses the default queue_mode='my': the test admin user has no
        workcenters assigned, so the queue is empty and no switch occurs.
        """
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        # Default queue_mode is 'my' → no workcenters → empty queue.
        self.assertEqual(wiz.queue_mode, "my")
        res = wiz.action_finish_production()
        self.assertTrue(res)
        # No switch → wizard stays on the done MO.
        self.assertEqual(wiz.production_id, self.production)
        self.assertIn("No more MOs", wiz.message)
        self.assertEqual(self.production.state, "done")

    def test_t3_finish_backorder_switches_to_new_mo(self):
        """Direction B: partial finish auto-creates a backorder (create
        _backorder='always') and the wizard switches to the new backorder
        MO so the operator keeps scanning without leaving the interface.
        """
        self.production.picking_type_id.create_backorder = "always"
        self._scan_component(
            self.production, self.component_tracked,
            "PROD-COMP-T", 0.8, lot_barcode="LOT-COMP-001",
        )
        wiz = self.WizScanMrp.create({
            "production_id": self.production.id,
        })
        wiz.queue_mode = "all"
        wiz.finished_qty_producing = 0.4
        res = wiz.action_finish_production()
        # Backorder auto-created → True (not a dialog), wizard switched.
        self.assertTrue(res is True)
        self.assertEqual(self.production.state, "done")
        self.assertNotEqual(wiz.production_id, self.production)
        # New MO is the backorder with the remaining quantity.
        self.assertEqual(wiz.production_id.product_qty, 0.6)
        self.assertIn(wiz.production_id.state, ("confirmed", "progress", "to_close"))

    # --- Task 4: cross-product SN collision disambiguation ---

    COLLIDE_LOT = "T4-COLLIDE-001"

    def _t4_add_colliding_component(self, name, barcode):
        """Add a tracked component that has a lot sharing the collision
        name T4-COLLIDE-001 (different from component_tracked's
        LOT-COMP-001, so _scan_lot misses and falls back)."""
        comp = self.Product.create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": barcode,
        })
        self.StockProductionLot.create({
            "name": self.COLLIDE_LOT,
            "product_id": comp.id,
            "company_id": self.company.id,
        })
        self.env["stock.move"].create({
            "product_id": comp.id,
            "product_uom_qty": 1.0,
            "product_uom": comp.uom_id.id,
            "raw_material_production_id": self.production.id,
            "location_id": self.components_location.id,
            "location_dest_id": comp.property_stock_production.id,
            "date": "2026-09-23 00:00:00",
            "company_id": self.company.id,
            "procure_method": "make_to_order",
        })
        return comp

    def test_t4_collision_resolved_by_current_product(self):
        """Cross-product SN collision: with product_id set to one of the
        colliding products, the scan binds that product's lot directly."""
        comp_c = self._t4_add_colliding_component("Component C Tracked", "PROD-COMP-C")
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        # Lock to comp_c
        self.action_barcode_scanned(wiz, "PROD-COMP-C")
        self.assertEqual(wiz.product_id, comp_c)
        # Scan the colliding SN → _scan_lot finds comp_c's lot directly
        self.action_barcode_scanned(wiz, self.COLLIDE_LOT)
        self.assertEqual(wiz.lot_id.product_id, comp_c)
        self.assertEqual(wiz.product_id, comp_c)
        self.assertNotEqual(wiz.message_type, "more_match")

    def test_t4_collision_ambiguous_without_context(self):
        """Cross-product SN collision: product_id set to a product that
        does NOT own the collision lot → fallback finds 2 lots, both are
        MO components → genuine ambiguity → more_match."""
        # Two components both own a lot named T4-COLLIDE-001
        self._t4_add_colliding_component("Component D Tracked", "PROD-COMP-D")
        self._t4_add_colliding_component("Component D2 Tracked", "PROD-COMP-D2")
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        # Lock to component_tracked (owns LOT-COMP-001, not T4-COLLIDE-001)
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        self.assertEqual(wiz.product_id, self.component_tracked)
        # Scan collision SN → _scan_lot misses → fallback → 2 lots → more_match
        self.action_barcode_scanned(wiz, self.COLLIDE_LOT)
        self.assertEqual(wiz.message_type, "more_match")
        self.assertFalse(wiz.lot_id)

    def test_t4_active_move_disambiguates(self):
        """With active_move_id set (and product_id unset), scanning a
        colliding SN binds the lot of the active move's product."""
        comp_c = self._t4_add_colliding_component(
            "Component E Tracked", "PROD-COMP-E"
        )
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        # product_id intentionally NOT set; rely on active_move_id
        move_c = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == comp_c
        )
        self.assertTrue(wiz.set_active_move(move_c.id))
        self.assertEqual(wiz.active_move_id, move_c)
        # Scan collision SN → _scan_lot uses active_move's product → binds
        self.action_barcode_scanned(wiz, self.COLLIDE_LOT)
        self.assertEqual(wiz.product_id, comp_c)
        self.assertEqual(wiz.lot_id.product_id, comp_c)

    def test_t4_no_collision_normal_binding(self):
        """Regression: a single (non-colliding) lot binds normally even
        with active_move_id unset."""
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
        self.action_barcode_scanned(wiz, "PROD-COMP-T")
        # LOT-COMP-001 is unique to component_tracked in this MO
        self.action_barcode_scanned(wiz, "LOT-COMP-001")
        self.assertEqual(wiz.lot_id, self.component_lot)
        self.assertEqual(wiz.message_type, "info")

    def test_t4_set_active_move_rejects_foreign_move(self):
        """set_active_move rejects a move that does not belong to the
        current MO's raw materials."""
        other_mo = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "product_uom_id": self.finished_product.uom_id.id,
        })
        other_mo.action_confirm()
        other_move = other_mo.move_raw_ids[:1]
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        self.assertFalse(wiz.set_active_move(other_move.id))
        self.assertFalse(wiz.active_move_id)

    def test_t4_active_move_cleared_on_mo_switch(self):
        """Switching to another MO clears the active_move_id."""
        comp_c = self._t4_add_colliding_component(
            "Component F Tracked", "PROD-COMP-F"
        )
        wiz = self.WizScanMrp.create({"production_id": self.production.id})
        move_c = self.production.move_raw_ids.filtered(
            lambda m: m.product_id == comp_c
        )
        wiz.set_active_move(move_c.id)
        self.assertTrue(wiz.active_move_id)
        # Create + confirm another MO and switch to it
        other_mo = self.MrpProduction.create({
            "product_id": self.finished_product.id,
            "product_qty": 1.0,
            "product_uom_id": self.finished_product.uom_id.id,
        })
        other_mo.action_confirm()
        wiz._switch_production(other_mo)
        self.assertFalse(wiz.active_move_id)

    # ------------------------------------------------------------------
    # Task 5: serial SN auto-consume (one SN = one physical unit)
    # ------------------------------------------------------------------
    def _t5_make_serial_component_mo(self, demand):
        """Create an MO with a serial-tracked component at `demand`.

        Returns (mo, component, [lot1, lot2, ...]). The component has stock
        in self.components_location so the raw move is reserved.
        """
        comp = self.Product.create({
            "name": "Serial Comp T5",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-COMP-SER-T5",
        })
        lots = []
        for i in range(1, 4):
            lot = self.StockProductionLot.create({
                "name": "SN-T5-%03d" % i,
                "product_id": comp.id,
                "company_id": self.company.id,
            })
            self.StockQuant.create({
                "product_id": comp.id,
                "lot_id": lot.id,
                "location_id": self.components_location.id,
                "quantity": 1.0,
            })
            lots.append(lot)
        finished = self.Product.create({
            "name": "Serial Fin T5",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-FIN-SER-T5",
        })
        bom = self.MrpBom.create({
            "product_id": finished.id,
            "product_tmpl_id": finished.product_tmpl_id.id,
            "type": "normal",
            "bom_line_ids": [(0, 0, {
                "product_id": comp.id,
                "product_qty": demand,
                "product_uom_id": comp.uom_id.id,
            })],
        })
        mo = self.MrpProduction.create({
            "product_id": finished.id,
            "product_qty": 1.0,
            "bom_id": bom.id,
            "location_src_id": self.components_location.id,
            "location_dest_id": self.finished_location.id,
        })
        mo.action_confirm()
        return mo, comp, lots

    def test_t5_serial_auto_consume_on_scan(self):
        """Scanning a serial SN auto-consumes qty=1 without manual Confirm.

        After the scan the wizard is back to a clean state (step 2, no
        product/lot) so the operator can scan the next component/SN.
        """
        mo, comp, lots = self._t5_make_serial_component_mo(demand=1.0)
        wiz = self.WizScanMrp.create({"production_id": mo.id})
        # Scan the component product barcode, then its SN
        self.action_barcode_scanned(wiz, "PROD-COMP-SER-T5")
        self.action_barcode_scanned(wiz, lots[0].name)
        # Auto-consume happened: state is cleaned
        self.assertFalse(wiz.product_id)
        self.assertFalse(wiz.lot_id)
        self.assertEqual(wiz.step, 2)
        # The SN was consumed as a move line of qty 1
        move = mo.move_raw_ids.filtered(lambda m: m.product_id == comp)
        sn_line = move.move_line_ids.filtered(lambda l: l.lot_id == lots[0])
        self.assertTrue(sn_line)
        self.assertEqual(sn_line.quantity, 1.0)
        self.assertTrue(sn_line.picked)

    def test_t5_serial_two_sns_accumulate(self):
        """Scanning two different serial SNs for demand=2 creates two lines.

        Each SN is one physical unit; the second scan must add a new move
        line, not overwrite the first one.
        """
        mo, comp, lots = self._t5_make_serial_component_mo(demand=2.0)
        wiz = self.WizScanMrp.create({"production_id": mo.id})
        # First SN: scan product then SN (auto-consume cleans state to step 2)
        self.action_barcode_scanned(wiz, "PROD-COMP-SER-T5")
        self.action_barcode_scanned(wiz, lots[0].name)
        # Second SN: re-scan product barcode (state was cleaned), then SN
        self.action_barcode_scanned(wiz, "PROD-COMP-SER-T5")
        self.action_barcode_scanned(wiz, lots[1].name)
        move = mo.move_raw_ids.filtered(lambda m: m.product_id == comp)
        consumed = move.move_line_ids.filtered(lambda l: l.picked)
        self.assertEqual(len(consumed), 2)
        consumed_lots = consumed.mapped("lot_id")
        self.assertIn(lots[0], consumed_lots)
        self.assertIn(lots[1], consumed_lots)
        self.assertEqual(consumed.mapped("quantity"), [1.0, 1.0])

    def test_t5_serial_overscan_triggers_force_not_eat(self):
        """Over-scanning (demand=1, two different SNs) triggers Force and
        does NOT silently eat the first scanned SN line.
        """
        mo, comp, lots = self._t5_make_serial_component_mo(demand=1.0)
        wiz = self.WizScanMrp.create({"production_id": mo.id})
        self.action_barcode_scanned(wiz, "PROD-COMP-SER-T5")
        self.action_barcode_scanned(wiz, lots[0].name)
        # First SN consumed
        move = mo.move_raw_ids.filtered(lambda m: m.product_id == comp)
        self.assertTrue(move.move_line_ids.filtered(
            lambda l: l.lot_id == lots[0] and l.picked))
        # Second different SN: re-scan product (state cleaned), demand already
        # met -> Force is triggered and the first SN line is NOT eaten.
        self.action_barcode_scanned(wiz, "PROD-COMP-SER-T5")
        self.action_barcode_scanned(wiz, lots[1].name)
        self.assertTrue(wiz.visible_force_done)
        first_line = move.move_line_ids.filtered(lambda l: l.lot_id == lots[0])
        self.assertTrue(first_line, "First scanned SN must not be eaten")
        self.assertEqual(first_line.quantity, 1.0)
        second_line = move.move_line_ids.filtered(lambda l: l.lot_id == lots[1])
        self.assertFalse(second_line, "Second SN must not be written before Force")

    # ------------------------------------------------------------------
    # T6 — Direction B: serial SN written to MO immediately on scan
    # ------------------------------------------------------------------

    def _t6_open_serial_wizard(self):
        """Open a fresh wizard on the serial production MO."""
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "production_id": self.production_serial.id,
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            "res_id": self.production_serial.id,
        })
        return wiz

    def test_t6_serial_scan_existing_lot_writes_mo_immediately(self):
        wiz = self._t6_open_serial_wizard()
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, self.finished_lot_serial.name)
        # Direction B: MO.lot_producing_ids is populated immediately.
        self.assertEqual(wiz.production_id.lot_producing_ids, self.finished_lot_serial)
        self.assertEqual(wiz.finished_lot_id, self.finished_lot_serial)
        self.assertEqual(wiz.finished_qty_producing, 1.0)

    def test_t6_serial_scan_new_sn_writes_mo_immediately(self):
        wiz = self._t6_open_serial_wizard()
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-NEW-001")
        self.assertEqual(len(wiz.production_id.lot_producing_ids), 1)
        self.assertEqual(wiz.production_id.lot_producing_ids.name, "SN-SER-NEW-001")
        self.assertEqual(wiz.finished_qty_producing, 1.0)

    def test_t6_serial_rescan_replaces_lot(self):
        wiz = self._t6_open_serial_wizard()
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-RES-001")
        first = wiz.production_id.lot_producing_ids
        self.assertEqual(first.name, "SN-SER-RES-001")
        # Re-scan product (state cleaned) then a different SN replaces it.
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-RES-002")
        replaced = wiz.production_id.lot_producing_ids
        self.assertEqual(len(replaced), 1)
        self.assertEqual(replaced.name, "SN-SER-RES-002")

    def test_t6_lot_tracking_keeps_two_phase(self):
        wiz = self.env["wiz.stock.barcodes.mrp"].create({
            "production_id": self.production_tracked.id,
            "res_model_id": self.env.ref("mrp.model_mrp_production").id,
            "res_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, self.finished_product_tracked.barcode)
        self.action_barcode_scanned(wiz, self.finished_lot.name)
        # Lot-tracked: MO stays empty until Apply Lot.
        self.assertFalse(wiz.production_id.lot_producing_ids)
        self.assertTrue(wiz.finished_lot_id)

    def test_t6_finish_without_apply_still_works(self):
        wiz = self._t6_open_serial_wizard()
        original_mo = wiz.production_id
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-FIN-001")
        # Serial: MO already has the lot. Finish directly (no Apply click).
        self.assertEqual(len(original_mo.lot_producing_ids), 1)
        # Consume enough for 1 unit (component_simple is non-tracked,
        # _auto_fill_components marks reserved move lines picked).
        result = wiz.action_finish_production()
        self.assertTrue(result is True)
        # product_qty=3, qty_producing=1 → backorder created, wizard
        # switched to it. The original MO must be done.
        self.assertEqual(original_mo.state, "done")

    def test_t6_backorder_jumps_to_new_mo(self):
        wiz = self._t6_open_serial_wizard()
        wiz.production_id.picking_type_id.create_backorder = "always"
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-BO-001")
        # product_qty=3, qty_producing=1 -> backorder for 2 is auto-created.
        result = wiz.action_finish_production()
        self.assertTrue(result is True)
        # Wizard switched to the backorder MO (product_qty == 2).
        self.assertEqual(wiz.production_id.product_qty, 2.0)
        self.assertIn(wiz.production_id.state, ("confirmed", "progress", "to_close"))

    def test_t6_clean_clears_mo_lot_for_serial(self):
        wiz = self._t6_open_serial_wizard()
        self.action_barcode_scanned(wiz, self.finished_product_serial.barcode)
        self.action_barcode_scanned(wiz, "SN-SER-CLEAN-001")
        self.assertTrue(wiz.production_id.lot_producing_ids)
        wiz.action_clean_finished_lot()
        # Direction B + option A: Clean also clears the MO binding.
        self.assertFalse(wiz.production_id.lot_producing_ids)
        self.assertFalse(wiz.finished_lot_id)
