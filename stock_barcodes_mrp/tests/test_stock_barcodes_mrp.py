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
        self.assertEqual(action["res_model"], "wiz.stock.barcodes.mrp")
        wiz = self.WizScanMrp.browse(action["res_id"])
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

    def test_22_finish_production_full_flow(self):
        """Scan components, apply finished lot, finish -> MO done."""
        wiz = self.WizScanMrp.create({
            "production_id": self.production_tracked.id,
        })
        self.action_barcode_scanned(wiz, "LOC-COMP-001")
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
        # Scan finished lot -> still step 0 until it is applied
        self.action_barcode_scanned(wiz, "LOT-FIN-001")
        self.assertEqual(wiz.finished_lot_id, self.finished_lot)
        self.assertEqual(wiz.step, 0)
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
