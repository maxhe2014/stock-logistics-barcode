# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestStockBarcodesPicking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        group_stock_user = cls.env.ref("stock.group_stock_user")
        cls.env.user.group_ids = [(4, group_stock_user.id)]

        cls.StockLocation = cls.env["stock.location"]
        cls.Product = cls.env["product.product"]
        cls.StockQuant = cls.env["stock.quant"]
        cls.StockPicking = cls.env["stock.picking"]
        cls.StockMove = cls.env["stock.move"]
        cls.Wiz = cls.env["wiz.stock.barcodes.picking"]

        cls.warehouse = cls.env.ref("stock.warehouse0")
        cls.stock_location = cls.env.ref("stock.stock_location_stock")
        cls.stock_location.barcode = "LOC-STOCK-01"
        cls.customer_location = cls.env.ref("stock.stock_location_customers")

        cls.picking_type = cls.env["stock.picking.type"].search(
            [("code", "=", "outgoing")], limit=1
        )
        # Tests assume source-location scanning is mandatory (the
        # pre-feature default). Existing DB rows may carry NULL → False
        # for the new config field, so set it explicitly.
        cls.picking_type.barcode_scan_source_location = True
        cls.picking_type.barcode_scan_dest_location = False
        # Tests create new lots/serials on the fly, so the operation
        # type must allow it (use_create_lots). Without this the scan
        # flow rejects unknown barcodes with "does not exist".
        cls.picking_type.use_create_lots = True

        # Product without tracking
        cls.product_simple = cls.Product.create({
            "name": "Simple Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-SIMPLE-01",
        })

        # Product with lot tracking
        cls.product_lot = cls.Product.create({
            "name": "Lot Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-LOT-01",
        })

    def _open_selector(self, wiz, candidates):
        """Simulate the multi-match state that _scan_picking produces:
        populate pending candidates and open the selector.

        picking.name is unique per company, so a true cross-company
        multi-match requires a second company (heavy via account module).
        The multi-match branch itself only sets these two fields, so we
        exercise the selector/guard/select machinery directly.
        """
        wiz.pending_switch_picking_ids = [(6, 0, candidates.ids)]
        wiz.visible_switch_selector = True
        wiz._set_message(
            "more_match",
            self.env._("Multiple transfers found. Select one."),
        )

    def _create_picking(self, product, qty=10.0, location=None):
        src = location or self.stock_location
        self.StockQuant._update_available_quantity(product, src, 100.0)
        picking = self.StockPicking.create({
            "picking_type_id": self.picking_type.id,
            "location_id": src.id,
            "location_dest_id": self.customer_location.id,
            "partner_id": self.env["res.partner"].search([], limit=1).id,
        })
        self.StockMove.create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": src.id,
            "location_dest_id": self.customer_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _create_wiz(self, picking):
        wiz = self.Wiz.create({"picking_id": picking.id})
        wiz._set_default_values()
        return wiz

    def _create_serial_product(self, name, barcode):
        return self.Product.create({
            "name": name,
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": barcode,
        })

    def _create_lot(self, product, name):
        return self.env["stock.lot"].create({
            "name": name,
            "product_id": product.id,
            "company_id": self.env.company.id,
        })

    def _create_out_picking(self, product, qty=1.0):
        """Outgoing picking without pre-filling stock, so serial quantities
        stay exactly as the test sets them."""
        picking = self.StockPicking.create({
            "picking_type_id": self.picking_type.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
            "partner_id": self.env["res.partner"].search([], limit=1).id,
        })
        self.StockMove.create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    # --- SET semantics ---
    def test_set_semantics_replace_quantity(self):
        """Re-scanning a product with a different qty SETS (not ADDS).

        Scanning qty=5 then qty=3 must leave a single move line with
        quantity 3.0, not 8.0 across multiple lines.
        """
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 5.0
        self.assertTrue(wiz.action_confirm())

        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids[0].quantity, 5.0)

        # Re-scan with qty=3 → SET, not ADD
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 3.0
        self.assertTrue(wiz.action_confirm())

        self.assertEqual(len(move.move_line_ids), 1)
        self.assertEqual(move.move_line_ids[0].quantity, 3.0)

    def test_set_semantics_overdemand_blocks(self):
        """Qty exceeding demand is blocked unless force_done is used."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 99.0
        self.assertFalse(wiz.action_confirm())
        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_done)

    # --- picked dual-write constraint ---
    def test_picked_dual_write(self):
        """Both line.picked and move.picked must be True after confirm.

        Without move.picked, _get_picked_quantity ignores the line and
        _check_backorder prompts for a backorder even though all demand
        is picked.
        """
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 10.0
        self.assertTrue(wiz.action_confirm())

        line = move.move_line_ids[0]
        self.assertTrue(line.picked, "move line must be picked")
        self.assertTrue(move.picked, "parent move must be picked")

    def test_overdemand_force_done_succeeds(self):
        """force_done context bypasses the demand cap."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 99.0
        self.assertFalse(wiz.action_confirm())
        # Force done bypasses the cap
        self.assertTrue(wiz.action_force_done())
        self.assertEqual(move.move_line_ids[0].quantity, 99.0)

    # --- over-picking policy (picking type setting) ---
    def test_excess_policy_allow_adds_and_notifies(self):
        """Policy 'allow' adds the excess directly and mentions it."""
        self.picking_type.barcode_excess_qty_policy = "allow"
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 12.0
        self.assertTrue(wiz.action_confirm())

        self.assertEqual(move.move_line_ids[0].quantity, 12.0)
        self.assertEqual(wiz.message_type, "success")
        self.assertIn("over demand", wiz.message)
        self.assertFalse(wiz.visible_force_done)

    def test_excess_policy_forbid_rejects(self):
        """Policy 'forbid' rejects the scan and blocks force_done."""
        self.picking_type.barcode_excess_qty_policy = "forbid"
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        reserved_qty = sum(l.quantity for l in move.move_line_ids)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 12.0
        self.assertFalse(wiz.action_confirm())

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("forbidden", wiz.message)
        self.assertFalse(wiz.visible_force_done)
        self.assertEqual(
            sum(l.quantity for l in move.move_line_ids), reserved_qty
        )
        # A direct RPC call must not bypass the policy either.
        self.assertFalse(wiz.action_force_done())
        self.assertEqual(wiz.message_type, "error")

    def test_excess_policy_forbid_blocks_extra_serial(self):
        """Policy 'forbid' rejects a serial above the remaining demand."""
        self.picking_type.barcode_excess_qty_policy = "forbid"
        product = self._create_serial_product(
            "Serial Forbid", "PROD-SN-FORBID"
        )
        lot_1 = self._create_lot(product, "SN-FORBID-001")
        lot_2 = self._create_lot(product, "SN-FORBID-002")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot_1
        )
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot_2
        )
        picking = self._create_out_picking(product, qty=1.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned(lot_1.name)
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 1.0
        )

        wiz.on_barcode_scanned(lot_2.name)
        self.assertEqual(wiz.message_type, "error")
        self.assertIn("forbidden", wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot_2)
        )

    # --- Location must-scan enforcement ---
    def test_confirm_without_location_fails(self):
        """action_confirm must reject when no source location was scanned.

        _set_default_values keeps location_id=False; the operator must
        scan the source location. Confirming without it errors out.
        """
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        # Do NOT scan location — go straight to product
        wiz.on_barcode_scanned(self.product_simple.barcode)
        wiz.product_qty = 5.0
        self.assertFalse(wiz.action_confirm())
        self.assertEqual(wiz.message_type, "error")

    # --- Switch picking clears location ---
    def test_switch_picking_clears_location(self):
        """Switching pickings must reset location_id to False.

        After scanning a location on picking A and switching to picking B
        (with a different source location), the wizard must not leak
        picking A's scanned location. location_id must be False and step
        must be back to 'location' so the operator re-scans.
        """
        # A second internal stock location with its own barcode
        loc_b = self.env["stock.location"].create({
            "name": "Stock B",
            "usage": "internal",
            "barcode": "LOC-STOCK-02",
            "location_id": self.stock_location.location_id.id,
        })
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0, location=loc_b)
        wiz = self._create_wiz(picking_a)

        # Scan location A
        wiz.on_barcode_scanned(self.stock_location.barcode)
        self.assertEqual(wiz.location_id, self.stock_location)

        # Switch to picking B by scanning its name (covers _scan_picking
        # dispatch, not just _switch_picking directly). on_barcode_scanned
        # returns None by design; verify side effects instead.
        wiz.on_barcode_scanned(picking_b.name)
        self.assertEqual(wiz.picking_id, picking_b,
                         "_scan_picking should match picking_b.name")
        self.assertFalse(wiz.location_id,
                         "location_id must be cleared on switch")
        self.assertEqual(wiz.step, wiz._step_index("location"),
                         "step must reset to location")

    # --- Multi-match candidate selector ---
    def test_multi_match_opens_selector(self):
        """A multi-match populates the candidate selector with both
        pickings and sets more_match."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)

        self._open_selector(wiz, picking_a | picking_b)
        self.assertTrue(wiz.visible_switch_selector)
        self.assertEqual(
            set(wiz.pending_switch_picking_ids.ids),
            {picking_a.id, picking_b.id},
        )
        self.assertEqual(wiz.message_type, "more_match")

    def test_multi_match_blocks_product_scan(self):
        """While the selector is open, product scans are blocked (cannot
        write to the wrong picking)."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)
        self._open_selector(wiz, picking_a | picking_b)
        self.assertTrue(wiz.visible_switch_selector)

        # Scanning a product while selector open must NOT write to picking_a
        wiz.on_barcode_scanned(self.product_simple.barcode)
        self.assertEqual(wiz.message_type, "error")
        self.assertFalse(wiz.product_id)

    def test_select_picking_candidate_switches(self):
        """Picking a candidate switches to it and closes the selector."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)
        self._open_selector(wiz, picking_a | picking_b)

        self.assertTrue(wiz.select_picking_candidate(picking_b.id))
        self.assertEqual(wiz.picking_id, picking_b)
        self.assertFalse(wiz.visible_switch_selector)
        self.assertFalse(wiz.pending_switch_picking_ids)

    def test_select_picking_candidate_rejects_foreign(self):
        """A picking id not in the candidate list is rejected."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        picking_c = self._create_picking(self.product_simple, qty=3.0)
        wiz = self._create_wiz(picking_a)
        self._open_selector(wiz, picking_a | picking_b)
        # picking_c is not a candidate
        self.assertFalse(wiz.select_picking_candidate(picking_c.id))

    def test_scan_picking_multi_match_populates_candidates(self):
        """_scan_picking's multi-match branch fills candidates from the
        search result (which is filtered to active states by its domain).

        picking.name is unique per company, so we patch stock.picking.search
        to return two active pickings and verify the selector gets both.
        """
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)

        fake_result = picking_a | picking_b
        with patch.object(
            type(self.env["stock.picking"]),
            "search",
            return_value=fake_result,
        ):
            wiz._scan_picking("AMBIG-BARCODE")

        self.assertTrue(wiz.visible_switch_selector)
        self.assertEqual(
            set(wiz.pending_switch_picking_ids.ids),
            {picking_a.id, picking_b.id},
        )
        self.assertEqual(wiz.message_type, "more_match")

    def test_selector_guard_blocks_actions(self):
        """Action RPCs are blocked while the selector is open so the old
        picking cannot be mutated."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)
        self._open_selector(wiz, picking_a | picking_b)

        # All mutating actions must return False with an error
        self.assertFalse(wiz.action_confirm())
        self.assertEqual(wiz.message_type, "error")
        self.assertFalse(wiz.action_consume_by_demand())
        self.assertFalse(wiz.action_consume_with_qty(1.0))
        self.assertFalse(wiz.action_force_add(self.product_simple.id))
        self.assertFalse(wiz.action_force_add_from_barcode("WHATEVER"))
        self.assertFalse(wiz.action_validate_picking())
        self.assertFalse(wiz.set_active_move(picking_a.move_ids[0].id))
        # action_force_done delegates to action_confirm, so it must also
        # be blocked (guards the against a future refactor that bypasses
        # action_confirm).
        self.assertFalse(wiz.action_force_done())

    # --- Step routing ---
    def test_nontracked_skips_lot_step(self):
        """Non-tracked products jump from product step directly to qty."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        # qty is index 3 in ['location','product','lot','qty']
        self.assertEqual(wiz.step, wiz._step_index("qty"))
        self.assertEqual(wiz.product_tracking, "none")

    def test_tracked_goes_to_lot_step(self):
        """Lot-tracked products go to the lot step after product scan."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(self.product_lot.barcode)
        self.assertEqual(wiz.step, wiz._step_index("lot"))
        self.assertEqual(wiz.product_tracking, "lot")

    def test_clean_values_resets_product_tracking(self):
        """_clean_values clears product_id so product_tracking (related)
        empties and the lot step becomes visible again."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        self.assertEqual(wiz.product_tracking, "none")
        wiz.product_qty = 1.0
        wiz.action_confirm()
        # After _clean_values, product_id is False → product_tracking empty
        self.assertFalse(wiz.product_id)
        self.assertFalse(wiz.product_tracking)

    # --- _scan_location ---
    def test_scan_location_advances_to_product_step(self):
        """Scanning a location barcode sets location_id and advances step
        from location (0) to product (1)."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        # After _set_default_values, step = location
        self.assertEqual(wiz.step, wiz._step_index("location"))

        wiz.on_barcode_scanned(self.stock_location.barcode)
        self.assertEqual(wiz.location_id, self.stock_location)
        self.assertEqual(wiz.step, wiz._step_index("product"))

    # --- Tracked full flow ---
    def test_tracked_lot_full_flow(self):
        """product → lot → qty → confirm for a lot-tracked product."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)

        # Step 1: scan location
        wiz.on_barcode_scanned(self.stock_location.barcode)
        self.assertEqual(wiz.step, wiz._step_index("product"))

        # Step 2: scan product
        wiz.on_barcode_scanned(self.product_lot.barcode)
        self.assertEqual(wiz.product_id, self.product_lot)
        self.assertEqual(wiz.step, wiz._step_index("lot"))

        # Step 3: scan an unknown lot name → creates new lot, goes to qty
        wiz.on_barcode_scanned("NEW-LOT-001")
        self.assertTrue(wiz.lot_name, "lot_name should be set")
        self.assertEqual(wiz.step, wiz._step_index("qty"))

        # Step 4: set qty and confirm
        wiz.product_qty = 3.0
        self.assertTrue(wiz.action_confirm())
        line = move.move_line_ids.filtered(lambda l: l.lot_id)
        self.assertTrue(line)
        self.assertEqual(line.lot_id.name, "NEW-LOT-001")
        self.assertEqual(line.quantity, 3.0)
        self.assertTrue(line.picked)
        self.assertTrue(move.picked)

    # --- New lot uniqueness ---
    def test_create_new_lot_search_then_create(self):
        """Scanning an unknown barcode creates a lot; scanning the same
        barcode again reuses it (search-then-create, no duplicate)."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        wiz.on_barcode_scanned("LOT-UNIQUE-001")
        # lot_id is set only during action_confirm (via _create_new_lot)
        self.assertFalse(wiz.lot_id)
        self.assertEqual(wiz.lot_name, "LOT-UNIQUE-001")
        wiz.product_qty = 1.0
        wiz.action_confirm()
        # _clean_values clears wiz.lot_id, so query by name
        lot_1 = self.env["stock.lot"].search([
            ("name", "=", "LOT-UNIQUE-001"),
            ("product_id", "=", self.product_lot.id),
        ])
        self.assertTrue(lot_1, "lot should be created on confirm")

        # Scan same lot barcode again
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        wiz.on_barcode_scanned("LOT-UNIQUE-001")
        # Search-then-create must reuse lot_1, not create a duplicate
        count = self.env["stock.lot"].search_count([
            ("name", "=", "LOT-UNIQUE-001"),
            ("product_id", "=", self.product_lot.id),
        ])
        self.assertEqual(count, 1)

    # --- _resolve_lot_owner: non-picking product ---
    def test_resolve_lot_owner_non_picking_product(self):
        """A lot belonging to a product NOT on this picking returns an
        error and does not switch product_id."""
        other_product = self.Product.create({
            "name": "Other Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-OTHER-01",
        })
        other_lot = self.env["stock.lot"].create({
            "name": "LOT-OTHER-001",
            "product_id": other_product.id,
            "company_id": self.env.company.id,
        })

        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        # Scan a lot that belongs to a product not on this picking
        result = wiz._scan_lot(other_lot.name)
        # _scan_lot should claim the barcode (return True) with error
        self.assertTrue(result)
        self.assertEqual(wiz.message_type, "error")
        self.assertNotEqual(wiz.product_id, other_product)

    # --- action_consume_by_demand ---
    def test_consume_by_demand_rejects_tracked(self):
        """Tracked products (lot/serial) cannot be consumed by demand."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        # product_lot has tracking='lot'
        self.assertFalse(wiz.action_consume_by_demand())
        self.assertEqual(wiz.message_type, "error")

    def test_consume_by_demand_non_tracked(self):
        """Non-tracked product consumes full move.product_uom_qty."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        result = wiz.action_consume_by_demand()
        self.assertTrue(result)
        line = move.move_line_ids[0]
        self.assertEqual(line.quantity, 10.0)
        self.assertTrue(line.picked)
        self.assertTrue(move.picked)

    def test_consume_by_demand_without_location_fails(self):
        """Consume by demand requires a scanned source location."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        self.assertFalse(wiz.action_consume_by_demand())

    # --- action_consume_with_qty ---
    def test_consume_with_qty(self):
        """Pencil-button consume with an explicit quantity."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.set_active_move(move.id)
        result = wiz.action_consume_with_qty(3.0)
        self.assertTrue(result)
        self.assertEqual(move.move_line_ids[0].quantity, 3.0)

    # --- set_active_move ---
    def test_set_active_move_rejects_foreign_move(self):
        """A move belonging to another picking cannot be set active."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)
        foreign_move = picking_b.move_ids[0]
        self.assertFalse(wiz.set_active_move(foreign_move.id))
        own_move = picking_a.move_ids[0]
        self.assertTrue(wiz.set_active_move(own_move.id))
        self.assertEqual(wiz.active_move_id, own_move)

    # --- Sticky product selection ---
    def test_serial_scan_keeps_active_move(self):
        """Scanning several serials of the same product keeps the row
        selected, so the operator does not have to re-click it each time."""
        product = self.Product.create({
            "name": "Serial Sticky Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-SERIAL-STICKY",
        })
        picking = self._create_picking(product, qty=3.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.set_active_move(move.id)

        wiz.on_barcode_scanned("SN-STICKY-001")
        self.assertEqual(wiz.active_move_id, move)
        self.assertEqual(
            sum(l.quantity for l in move.move_line_ids if l.picked), 1.0
        )

        wiz.on_barcode_scanned("SN-STICKY-002")
        self.assertEqual(wiz.active_move_id, move)
        self.assertEqual(
            sum(l.quantity for l in move.move_line_ids if l.picked), 2.0
        )
        # product_id is still cleaned after each confirm.
        self.assertFalse(wiz.product_id)

    def test_scan_other_product_switches_active_move(self):
        """Scanning another product's barcode switches the active row so
        serials of that product stay selected too."""
        product_a = self.Product.create({
            "name": "Serial A",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-SERIAL-A",
        })
        product_b = self.Product.create({
            "name": "Serial B",
            "type": "consu",
            "is_storable": True,
            "tracking": "serial",
            "barcode": "PROD-SERIAL-B",
        })
        self.StockQuant._update_available_quantity(product_a, self.stock_location, 5.0)
        self.StockQuant._update_available_quantity(product_b, self.stock_location, 5.0)
        picking = self.StockPicking.create({
            "picking_type_id": self.picking_type.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        })
        move_a = self.StockMove.create({
            "product_id": product_a.id,
            "product_uom_qty": 3.0,
            "product_uom": product_a.uom_id.id,
            "picking_id": picking.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        })
        move_b = self.StockMove.create({
            "product_id": product_b.id,
            "product_uom_qty": 3.0,
            "product_uom": product_b.uom_id.id,
            "picking_id": picking.id,
            "location_id": self.stock_location.id,
            "location_dest_id": self.customer_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.set_active_move(move_a.id)
        wiz.on_barcode_scanned("SN-A-001")
        self.assertEqual(wiz.active_move_id, move_a)

        wiz.on_barcode_scanned(product_b.barcode)
        self.assertEqual(wiz.active_move_id, move_b)
        wiz.on_barcode_scanned("SN-B-001")
        self.assertEqual(wiz.active_move_id, move_b)
        self.assertEqual(
            sum(l.quantity for l in move_b.move_line_ids if l.picked), 1.0
        )

    # --- Scan-time serial availability checks ---
    def test_scan_serial_from_other_location_rejected(self):
        """A serial stored in another internal location is rejected at
        scan time instead of failing only at validation."""
        product = self._create_serial_product(
            "Serial Elsewhere", "PROD-SN-ELSEWHERE"
        )
        lot = self._create_lot(product, "SN-ELSEWHERE-001")
        other_location = self.StockLocation.create({
            "name": "Other Stock",
            "usage": "internal",
            "location_id": self.warehouse.view_location_id.id,
        })
        self.StockQuant._update_available_quantity(
            product, other_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn(lot.name, wiz.message)
        self.assertIn(other_location.display_name, wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot),
            "the serial must not be added to the transfer",
        )

    def test_scan_delivered_serial_rejected(self):
        """A serial already at a customer location cannot be picked again."""
        product = self._create_serial_product(
            "Serial Delivered", "PROD-SN-DELIVERED"
        )
        lot = self._create_lot(product, "SN-DELIVERED-001")
        self.StockQuant._update_available_quantity(
            product, self.customer_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("already been delivered", wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        )

    def test_scan_serial_reserved_by_other_transfer_rejected(self):
        """A serial reserved by another transfer is rejected at scan time."""
        product = self._create_serial_product(
            "Serial Reserved", "PROD-SN-RESERVED"
        )
        lot = self._create_lot(product, "SN-RESERVED-001")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot
        )
        other_picking = self._create_out_picking(product)
        self.assertEqual(other_picking.move_line_ids.lot_id, lot)

        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("reserved by another transfer", wiz.message)
        self.assertIn(other_picking.name, wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        )

    def test_duplicate_serial_scan_warns(self):
        """Scanning the same serial twice must warn instead of silently
        ignoring the second scan."""
        product = self._create_serial_product(
            "Serial Duplicate", "PROD-SN-DUPLICATE"
        )
        lot = self._create_lot(product, "SN-DUPLICATE-001")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned(lot.name)
        lines = picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.picked)

        wiz.on_barcode_scanned(lot.name)
        self.assertEqual(wiz.message_type, "error")
        self.assertIn(lot.name, wiz.message)
        self.assertIn("already been added", wiz.message)
        lines = picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(lines), 1)
        self.assertEqual(sum(l.quantity for l in lines), 1.0)

    def test_scan_serial_without_product_auto_matches(self):
        """Scanning a serial alone selects its product and adds it."""
        product = self._create_serial_product(
            "Serial Auto", "PROD-SN-AUTO"
        )
        lot = self._create_lot(product, "SN-AUTO-001")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        # No product scan, no row selection: scan the serial only.
        wiz.on_barcode_scanned(lot.name)

        # product_id is reset after a successful confirm, but the row
        # highlight must stay on the matched product so the operator can
        # keep scanning its serials.
        self.assertEqual(wiz.active_move_id.product_id, product)
        self.assertEqual(wiz.message_type, "success")
        self.assertIn(product.name, wiz.message)
        self.assertIn(lot.name, wiz.message)
        lines = picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines.picked)
        self.assertEqual(sum(lines.mapped("quantity")), 1.0)

    def test_scan_serial_of_other_product_rejected(self):
        """A serial of a product outside the transfer is rejected."""
        in_picking_product = self._create_serial_product(
            "Serial In Picking", "PROD-SN-IN"
        )
        other_product = self._create_serial_product(
            "Serial Other", "PROD-SN-OUT"
        )
        lot = self._create_lot(other_product, "SN-OTHER-001")
        self.StockQuant._update_available_quantity(
            other_product, self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(in_picking_product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("not part of this transfer", wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        )

    def test_scan_unknown_serial_without_product_rejected(self):
        """With use_create_lots disabled, an unknown serial is rejected."""
        self.picking_type.use_create_lots = False
        product = self._create_serial_product(
            "Serial Unknown", "PROD-SN-UNKNOWN"
        )
        picking = self._create_out_picking(product)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned("SN-UNKNOWN-404")

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("does not exist", wiz.message)
        self.assertEqual(
            self.env["stock.lot"].search_count(
                [("name", "=", "SN-UNKNOWN-404")]
            ),
            0,
        )

    # --- action_force_add ---
    def test_force_add_creates_move_and_picks(self):
        """action_force_add adds a product NOT on the picking, creates a
        new move, and picks it."""
        # A second non-tracked product, not on the picking
        extra = self.Product.create({
            "name": "Extra Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-EXTRA-01",
        })
        self.StockQuant._update_available_quantity(extra, self.stock_location, 100.0)
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        # extra is not on the picking; pass product_id explicitly to
        # action_force_add (scanning it would not set product_id since it
        # is not part of the picking).
        wiz.product_qty = 2.0
        before = len(picking.move_ids)
        result = wiz.action_force_add(product_id=extra.id)
        self.assertTrue(result)
        # A new move was created and confirmed
        self.assertEqual(len(picking.move_ids), before + 1)
        new_move = picking.move_ids[-1]
        self.assertEqual(new_move.product_id, extra)
        self.assertEqual(new_move.location_dest_id, picking.location_dest_id)
        self.assertTrue(new_move.picked)

    def test_force_add_rejects_tracked(self):
        """action_force_add rejects tracked products."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        wiz.product_qty = 1.0
        self.assertFalse(wiz.action_force_add())

    # --- action_force_add_from_barcode (unmatched-barcode contract) ---
    def test_force_add_from_barcode(self):
        """Frontend passes an unmatched barcode; server resolves product
        and force-adds it."""
        extra = self.Product.create({
            "name": "Extra Product",
            "type": "consu",
            "is_storable": True,
            "tracking": "none",
            "barcode": "PROD-EXTRA-02",
        })
        self.StockQuant._update_available_quantity(extra, self.stock_location, 100.0)
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.product_qty = 3.0
        result = wiz.action_force_add_from_barcode(extra.barcode)
        self.assertTrue(result)
        new_move = picking.move_ids.filtered(lambda m: m.product_id == extra)
        self.assertTrue(new_move)
        self.assertTrue(new_move.picked)

    def test_force_add_from_barcode_unknown(self):
        """A barcode matching no product returns an error."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.product_qty = 1.0
        self.assertFalse(wiz.action_force_add_from_barcode("NO-SUCH-BARCODE"))
        self.assertEqual(wiz.message_type, "error")

    # --- stash / restore across pickings ---
    def test_stash_restore_on_switch_back(self):
        """In-progress scan is stashed on switch-away and restored on return."""
        picking_a = self._create_picking(self.product_simple, qty=10.0)
        picking_b = self._create_picking(self.product_simple, qty=5.0)
        wiz = self._create_wiz(picking_a)

        # Scan location + product on A (in-progress, not yet confirmed)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        self.assertTrue(wiz.product_id)

        # Switch to B → A's progress is stashed
        wiz._switch_picking(picking_b)
        self.assertFalse(wiz.product_id,
                         "B should start fresh (no stashed progress)")

        # Switch back to A → A's progress should be restored
        wiz._switch_picking(picking_a)
        self.assertTrue(wiz.product_id,
                        "A's in-progress product scan should be restored")
        self.assertEqual(wiz.step, wiz._step_index("qty"))

    # --- action_validate_picking integration ---
    def test_validate_after_full_consume(self):
        """Consume full demand then validate; should return True (no
        backorder wizard, proving picked dual-write works)."""
        picking = self._create_picking(self.product_simple, qty=10.0)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_simple.barcode)
        self.assertTrue(wiz.action_consume_by_demand())
        result = wiz.action_validate_picking()
        # True means validated directly. A dict means backorder wizard
        # (picked dual-write failed).
        self.assertIs(result, True)
        self.assertEqual(picking.state, "done")
