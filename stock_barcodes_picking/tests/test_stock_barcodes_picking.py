# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from unittest.mock import patch

from lxml import etree

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

    def _create_picked_lot_line(
        self, picking, lot, quantity, package=None, picked=True
    ):
        move = picking.move_ids.filtered(
            lambda m: m.product_id == lot.product_id
        )[:1]
        return self.env["stock.move.line"].create({
            "move_id": move.id,
            "picking_id": picking.id,
            "product_id": lot.product_id.id,
            "product_uom_id": lot.product_id.uom_id.id,
            "lot_id": lot.id,
            "quantity": quantity,
            "picked": picked,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "result_package_id": package.id if package else False,
        })

    def _prepare_outside_serial_scan(self, policy="allow", location=None):
        """Build an outgoing transfer and an outside serial ready to scan."""
        self.picking_type.barcode_new_product_policy = policy
        product = self._create_serial_product(
            "Outside Serial", "PROD-OUTSIDE-SERIAL"
        )
        lot = self._create_lot(product, "SN-OUTSIDE-001")
        self.StockQuant._update_available_quantity(
            product, location or self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(self.product_simple)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        return product, lot, picking, wiz

    def _prepare_outside_lot_scan(
        self, policy="allow", location=None, quantity=10.0
    ):
        """Build an outgoing transfer and an outside lot ready to scan."""
        self.picking_type.barcode_new_product_policy = policy
        product = self.Product.create({
            "name": "Outside Lot",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
            "barcode": "PROD-OUTSIDE-LOT",
        })
        lot = self._create_lot(product, "LOT-OUTSIDE-001")
        self.StockQuant._update_available_quantity(
            product, location or self.stock_location, quantity, lot_id=lot
        )
        picking = self._create_out_picking(self.product_simple)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        return product, lot, picking, wiz

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

    def _create_in_picking(self, product, return_of=None, qty=1.0):
        """Incoming picking for a supplier receipt or a customer return."""
        receipt_type = self.env.ref("stock.picking_type_in")
        receipt_type.barcode_scan_source_location = False
        receipt_type.barcode_scan_dest_location = False
        receipt_type.use_create_lots = True
        source = (
            self.customer_location
            if return_of
            else self.env.ref("stock.stock_location_suppliers")
        )
        picking = self.StockPicking.create({
            "picking_type_id": receipt_type.id,
            "location_id": source.id,
            "location_dest_id": self.stock_location.id,
            "return_id": return_of.id if return_of else False,
        })
        self.StockMove.create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": source.id,
            "location_dest_id": self.stock_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    # --- Operation type configuration ---
    def test_mrp_hides_picking_only_barcode_config(self):
        """Picking-only policies must not appear on manufacturing types."""
        self.env.user.group_ids = [
            (4, self.env.ref("stock.group_tracking_lot").id)
        ]
        view_id = self.env.ref(
            "stock_barcodes_picking.view_picking_type_form_inherit_barcode"
        ).id
        view = self.env["stock.picking.type"].get_view(
            view_id=view_id, view_type="form"
        )
        arch = etree.fromstring(view["arch"])
        for field_name in (
            "barcode_excess_qty_policy",
            "barcode_new_product_policy",
            "barcode_require_pack",
            "barcode_validation_all_packed",
        ):
            nodes = arch.xpath("//field[@name='%s']" % field_name)
            self.assertEqual(len(nodes), 1, field_name)
            self.assertEqual(
                nodes[0].getparent().get("invisible"),
                "code == 'mrp_operation'",
                field_name,
            )

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

    def test_excess_policy_allow_adds_extra_new_serial_on_receipt(self):
        """Allow must also apply after the receipt demand is fully picked."""
        receipt_type = self.env.ref("stock.picking_type_in")
        receipt_type.barcode_excess_qty_policy = "allow"
        receipt_type.use_create_lots = True
        receipt_type.barcode_scan_source_location = False
        receipt_type.barcode_scan_dest_location = False
        product = self._create_serial_product(
            "Receipt Serial Allow", "PROD-SN-RECEIPT-ALLOW"
        )
        supplier = self.env.ref("stock.stock_location_suppliers")
        picking = self.StockPicking.create({
            "picking_type_id": receipt_type.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        self.StockMove.create({
            "product_id": product.id,
            "product_uom_qty": 1.0,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned("SN-RECEIPT-ALLOW-001")
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 1.0
        )

        wiz.on_barcode_scanned("SN-RECEIPT-ALLOW-002")

        self.assertEqual(wiz.message_type, "success")
        self.assertIn("over demand", wiz.message)
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 2.0
        )
        self.assertTrue(
            picking.move_line_ids.filtered(
                lambda l: l.lot_id.name == "SN-RECEIPT-ALLOW-002" and l.picked
            )
        )

    def test_excess_policy_warn_allows_existing_serial_on_receipt(self):
        """Receipts must not require incoming serial stock at the vendor."""
        receipt_type = self.env.ref("stock.picking_type_in")
        receipt_type.barcode_excess_qty_policy = "warn"
        receipt_type.use_create_lots = True
        receipt_type.barcode_scan_source_location = False
        receipt_type.barcode_scan_dest_location = False
        product = self._create_serial_product(
            "Receipt Serial Warn", "PROD-SN-RECEIPT-WARN"
        )
        supplier = self.env.ref("stock.stock_location_suppliers")
        picking = self.StockPicking.create({
            "picking_type_id": receipt_type.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        self.StockMove.create({
            "product_id": product.id,
            "product_uom_qty": 1.0,
            "product_uom": product.uom_id.id,
            "picking_id": picking.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        picking.action_confirm()
        picking.action_assign()
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(product.barcode)
        wiz.on_barcode_scanned("SN-RECEIPT-WARN-001")
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 1.0
        )
        existing_lot = self.env["stock.lot"].create({
            "name": "SN-RECEIPT-WARN-002",
            "product_id": product.id,
            "company_id": False,
        })

        wiz.on_barcode_scanned(existing_lot.name)

        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_done)
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 1.0
        )
        wiz.action_force_done()
        self.assertFalse(wiz.visible_force_done)
        self.assertEqual(
            sum(l.quantity for l in picking.move_line_ids if l.picked), 2.0
        )

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
        """product → lot immediately creates and picks one unit."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(self.stock_location.barcode)
        self.assertEqual(wiz.step, wiz._step_index("product"))
        wiz.on_barcode_scanned(self.product_lot.barcode)
        self.assertEqual(wiz.product_id, self.product_lot)
        self.assertEqual(wiz.step, wiz._step_index("lot"))

        wiz.on_barcode_scanned("NEW-LOT-001")
        line = move.move_line_ids.filtered(lambda l: l.lot_id)
        self.assertTrue(line)
        self.assertEqual(line.lot_id.name, "NEW-LOT-001")
        self.assertEqual(line.quantity, 1.0)
        self.assertTrue(line.picked)
        self.assertTrue(move.picked)
        self.assertEqual(wiz.message_type, "success")
        self.assertIn("NEW-LOT-001", wiz.message)

    def test_new_lot_from_active_move_scans_accumulate_immediately(self):
        """Each scan immediately picks one more unit of the same new lot."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.set_active_move(move.id)
        self.assertFalse(wiz.product_id)
        self.assertEqual(wiz.product_qty, 0.0)

        for expected_qty in (1.0, 2.0, 3.0):
            wiz.on_barcode_scanned("TR-NEW-COUNT")
            lot = self.env["stock.lot"].search([
                ("name", "=", "TR-NEW-COUNT"),
                ("product_id", "=", self.product_lot.id),
            ])
            self.assertEqual(len(lot), 1)
            line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
            self.assertEqual(len(line), 1)
            self.assertEqual(line.quantity, expected_qty)
            self.assertTrue(line.picked)
            self.assertEqual(wiz.message_type, "success")
            self.assertIn("TR-NEW-COUNT", wiz.message)
            self.assertIn("Picked quantity", wiz.message)

    def test_multiple_lots_scans_accumulate_independently(self):
        """Interleaved lots of one product keep independent picked totals."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        wiz.set_active_move(move.id)

        for barcode in (
            "TR-MULTI-A", "TR-MULTI-B", "TR-MULTI-A",
            "TR-MULTI-B", "TR-MULTI-A",
        ):
            wiz.on_barcode_scanned(barcode)
            self.assertEqual(wiz.message_type, "success")

        picked_lines = move.move_line_ids.filtered(lambda l: l.lot_id and l.picked)
        quantities = {
            line.lot_id.name: line.quantity
            for line in picked_lines
        }
        self.assertEqual(quantities, {"TR-MULTI-A": 3.0, "TR-MULTI-B": 2.0})
        self.assertEqual(sum(picked_lines.mapped("quantity")), 5.0)

        # The scan state exposes each lot's actual picked quantity. A reserved
        # line of the same lot remains a separate pending entry with zero
        # picked quantity and a unique template key.
        picking.picking_type_id.barcode_show_reserved_sns = True
        lot_a = picked_lines.filtered(
            lambda l: l.lot_id.name == "TR-MULTI-A"
        ).lot_id
        self.env["stock.move.line"].create({
            "move_id": move.id,
            "picking_id": picking.id,
            "product_id": self.product_lot.id,
            "product_uom_id": self.product_lot.uom_id.id,
            "lot_id": lot_a.id,
            "quantity": 1.0,
            "picked": False,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
        })
        state_move = next(
            m for m in wiz.get_scan_state()["move_ids"] if m["id"] == move.id
        )
        self.assertEqual(state_move["quantity"], 5.0)
        self.assertEqual(len(state_move["lots"]), 3)
        self.assertEqual(
            {
                lot["name"]: lot["picked_quantity"]
                for lot in state_move["lots"]
                if lot["picked"]
            },
            {"TR-MULTI-A": 3.0, "TR-MULTI-B": 2.0},
        )
        reserved = next(lot for lot in state_move["lots"] if not lot["picked"])
        self.assertEqual(reserved["name"], "TR-MULTI-A")
        self.assertEqual(reserved["picked_quantity"], 0.0)
        self.assertEqual(
            len({lot["key"] for lot in state_move["lots"]}),
            len(state_move["lots"]),
        )

    def test_scan_state_lot_quantities_grouped_per_package(self):
        """Same-lot lines merge inside each package, not across packages."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        move = picking.move_ids[0]
        wiz = self._create_wiz(picking)
        lot = self._create_lot(self.product_lot, "TR-PACKAGE-QTY")
        package_1 = self.env["stock.package"].create({"name": "PKG-LOT-1"})
        package_2 = self.env["stock.package"].create({"name": "PKG-LOT-2"})
        for package, quantity in (
            (package_1, 2.0),
            (package_1, 3.0),
            (package_2, 4.0),
        ):
            self.env["stock.move.line"].create({
                "move_id": move.id,
                "picking_id": picking.id,
                "product_id": self.product_lot.id,
                "product_uom_id": self.product_lot.uom_id.id,
                "lot_id": lot.id,
                "quantity": quantity,
                "picked": True,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "result_package_id": package.id,
            })

        rows = [
            m for m in wiz.get_scan_state()["move_ids"] if m["id"] == move.id
        ]
        self.assertEqual(len(rows), 2)
        rows_by_package = {row["package_name"]: row for row in rows}
        self.assertEqual(rows_by_package["PKG-LOT-1"]["quantity"], 5.0)
        self.assertEqual(rows_by_package["PKG-LOT-2"]["quantity"], 4.0)
        self.assertEqual(
            rows_by_package["PKG-LOT-1"]["lots"][0]["picked_quantity"], 5.0
        )
        self.assertEqual(
            rows_by_package["PKG-LOT-2"]["lots"][0]["picked_quantity"], 4.0
        )
        self.assertEqual(len(rows_by_package["PKG-LOT-1"]["lots"]), 1)
        self.assertEqual(len(rows_by_package["PKG-LOT-2"]["lots"]), 1)
        package_1_lines = move.move_line_ids.filtered(
            lambda l: l.result_package_id == package_1
        ).sorted(key=lambda l: l.id)
        line_states = rows_by_package["PKG-LOT-1"]["lots"][0]["lines"]
        self.assertEqual(
            [line["id"] for line in line_states], package_1_lines.ids
        )
        self.assertEqual(
            [line["quantity"] for line in line_states], [2.0, 3.0]
        )
        for line_state in line_states:
            self.assertEqual(line_state["package_id"], package_1.id)
            self.assertEqual(line_state["package_name"], "PKG-LOT-1")
            self.assertEqual(
                line_state["location_name"], picking.location_id.display_name
            )

    def test_edit_lot_quantity_targets_exact_line(self):
        """Editing one of several same-lot lines leaves all others intact."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-EDIT-EXACT")
        line_1 = self._create_picked_lot_line(picking, lot, 2.0)
        line_2 = self._create_picked_lot_line(picking, lot, 3.0)
        wiz = self._create_wiz(picking)

        self.assertTrue(wiz.action_edit_move_line_qty(line_2.id, 7.0))

        self.assertEqual(line_1.quantity, 2.0)
        self.assertEqual(line_2.quantity, 7.0)

    def test_edit_lot_quantity_does_not_touch_other_package(self):
        """An explicit package-line edit cannot leak into another package."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-EDIT-PACKAGE")
        package_1 = self.env["stock.package"].create({"name": "PKG-EDIT-1"})
        package_2 = self.env["stock.package"].create({"name": "PKG-EDIT-2"})
        line_1 = self._create_picked_lot_line(
            picking, lot, 2.0, package=package_1
        )
        line_2 = self._create_picked_lot_line(
            picking, lot, 4.0, package=package_2
        )
        wiz = self._create_wiz(picking)

        self.assertTrue(wiz.action_edit_move_line_qty(line_2.id, 6.0))

        self.assertEqual(line_1.quantity, 2.0)
        self.assertEqual(line_2.quantity, 6.0)

    def test_lot_corrections_reject_foreign_and_unpicked_lines(self):
        """RPC IDs cannot cross pickings or modify reserved-only lines."""
        picking_a = self._create_in_picking(self.product_lot, qty=20.0)
        picking_b = self._create_in_picking(self.product_lot, qty=20.0)
        lot_a = self._create_lot(self.product_lot, "TR-EDIT-OWN")
        lot_b = self._create_lot(self.product_lot, "TR-EDIT-FOREIGN")
        reserved = self._create_picked_lot_line(
            picking_a, lot_a, 2.0, picked=False
        )
        foreign = self._create_picked_lot_line(picking_b, lot_b, 3.0)
        wiz = self._create_wiz(picking_a)

        self.assertFalse(wiz.action_edit_move_line_qty(foreign.id, 8.0))
        self.assertFalse(wiz.action_remove_move_lot(foreign.id))
        self.assertTrue(foreign.exists())
        self.assertEqual(foreign.quantity, 3.0)
        self.assertFalse(wiz.action_edit_move_line_qty(reserved.id, 8.0))
        self.assertFalse(wiz.action_remove_move_lot(reserved.id))
        self.assertTrue(reserved.exists())
        self.assertEqual(reserved.quantity, 2.0)
        self.assertFalse(reserved.picked)

    def test_lot_corrections_are_blocked_by_candidate_selector(self):
        """Edit and delete share the mutating-action selector guard."""
        picking_a = self._create_in_picking(self.product_lot, qty=20.0)
        picking_b = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-EDIT-SELECTOR")
        line = self._create_picked_lot_line(picking_a, lot, 4.0)
        wiz = self._create_wiz(picking_a)
        self._open_selector(wiz, picking_a | picking_b)

        self.assertFalse(wiz.action_edit_move_line_qty(line.id, 6.0))
        self.assertFalse(wiz.action_remove_move_lot(line.id))

        self.assertTrue(line.exists())
        self.assertEqual(line.quantity, 4.0)
        self.assertTrue(line.picked)
        self.assertEqual(wiz.message_type, "error")

    def test_edit_lot_quantity_follows_excess_policy(self):
        """Allow writes, warn needs force, and forbid always rejects."""
        for policy in ("allow", "warn", "forbid"):
            with self.subTest(policy=policy):
                picking = self._create_in_picking(self.product_lot, qty=10.0)
                picking.picking_type_id.barcode_excess_qty_policy = policy
                lot = self._create_lot(
                    self.product_lot, "TR-EDIT-POLICY-%s" % policy
                )
                other = self._create_picked_lot_line(picking, lot, 4.0)
                target = self._create_picked_lot_line(picking, lot, 2.0)
                wiz = self._create_wiz(picking)

                result = wiz.action_edit_move_line_qty(target.id, 8.0)

                if policy == "allow":
                    self.assertTrue(result)
                    self.assertEqual(target.quantity, 8.0)
                elif policy == "warn":
                    self.assertFalse(result)
                    self.assertEqual(wiz.message_type, "more_match")
                    self.assertEqual(target.quantity, 2.0)
                    self.assertTrue(
                        wiz.action_edit_move_line_qty(target.id, 8.0, force=True)
                    )
                    self.assertEqual(target.quantity, 8.0)
                else:
                    self.assertFalse(result)
                    self.assertEqual(wiz.message_type, "error")
                    self.assertFalse(
                        wiz.action_edit_move_line_qty(target.id, 8.0, force=True)
                    )
                    self.assertEqual(target.quantity, 2.0)
                self.assertEqual(other.quantity, 4.0)

    def test_edit_lot_quantity_requires_positive_number(self):
        """Zero and negative corrections never clear or alter a line."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-EDIT-POSITIVE")
        line = self._create_picked_lot_line(picking, lot, 3.0)
        wiz = self._create_wiz(picking)

        for qty in (0.0, -1.0):
            with self.subTest(qty=qty):
                self.assertFalse(wiz.action_edit_move_line_qty(line.id, qty))
                self.assertEqual(line.quantity, 3.0)
                self.assertEqual(wiz.message_type, "error")

    def test_serial_quantity_edit_rejected_and_delete_targets_exact_sn(self):
        """SN quantity stays fixed at 1 while its trash action still works."""
        product = self._create_serial_product(
            "Serial Exact Edit", "PROD-SN-EXACT-EDIT"
        )
        picking = self._create_in_picking(product, qty=2.0)
        lot_1 = self._create_lot(product, "SN-EXACT-EDIT-1")
        lot_2 = self._create_lot(product, "SN-EXACT-EDIT-2")
        line_1 = self._create_picked_lot_line(picking, lot_1, 1.0)
        line_2 = self._create_picked_lot_line(picking, lot_2, 1.0)
        wiz = self._create_wiz(picking)

        self.assertFalse(wiz.action_edit_move_line_qty(line_1.id, 1.0))
        self.assertEqual(line_1.quantity, 1.0)
        self.assertTrue(wiz.action_remove_move_lot(line_2.id))
        self.assertTrue(line_1.exists())
        self.assertFalse(line_2.exists())

    def test_remove_lot_uses_exact_line_and_keeps_decrement_semantics(self):
        """Trash decrements only its target line and unlinks it at qty 1."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-REMOVE-EXACT")
        line_1 = self._create_picked_lot_line(picking, lot, 3.0)
        line_2 = self._create_picked_lot_line(picking, lot, 1.0)
        wiz = self._create_wiz(picking)

        self.assertTrue(wiz.action_remove_move_lot(line_1.id))
        self.assertEqual(line_1.quantity, 2.0)
        self.assertEqual(line_2.quantity, 1.0)
        self.assertTrue(wiz.action_remove_move_lot(line_2.id))
        self.assertTrue(line_1.exists())
        self.assertFalse(line_2.exists())
        self.assertEqual(line_1.quantity, 2.0)
        self.assertTrue(wiz.action_remove_move_lot(line_1.id))
        self.assertEqual(line_1.quantity, 1.0)
        self.assertTrue(wiz.action_remove_move_lot(line_1.id))
        self.assertFalse(line_1.exists())
        self.assertTrue(lot.exists())

    def test_existing_lot_without_product_scan_accumulates(self):
        """Global lot fallback also picks immediately and then accumulates."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        move = picking.move_ids[0]
        lot = self._create_lot(self.product_lot, "TR-EXISTING-COUNT")
        wiz = self._create_wiz(picking)

        for expected_qty in (1.0, 2.0):
            wiz.on_barcode_scanned(lot.name)
            line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
            self.assertEqual(line.quantity, expected_qty)
            self.assertTrue(line.picked)
            self.assertEqual(wiz.message_type, "success")

    def test_scan_same_lot_after_packing_accumulates_unpacked_only(self):
        """Repeated scans start a new unpacked group without changing packages."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        move = picking.move_ids[0]
        lot = self._create_lot(self.product_lot, "TR-PACKED-SCAN-SAME")
        package_a = self.env["stock.package"].create({"name": "PKG-SCAN-A"})
        package_b = self.env["stock.package"].create({"name": "PKG-SCAN-B"})
        packed_a = self._create_picked_lot_line(
            picking, lot, 2.0, package=package_a
        )
        packed_b = self._create_picked_lot_line(
            picking, lot, 3.0, package=package_b
        )
        wiz = self._create_wiz(picking)

        for expected_qty in (1.0, 2.0):
            wiz.on_barcode_scanned(lot.name)
            unpacked = move.move_line_ids.filtered(
                lambda l: l.lot_id == lot and l.picked and not l.result_package_id
            )
            self.assertEqual(len(unpacked), 1)
            self.assertEqual(unpacked.quantity, expected_qty)
            self.assertEqual(packed_a.quantity, 2.0)
            self.assertEqual(packed_b.quantity, 3.0)
            self.assertEqual(packed_a.result_package_id, package_a)
            self.assertEqual(packed_b.result_package_id, package_b)
            self.assertEqual(wiz.message_type, "success")

        rows = [
            row for row in wiz.get_scan_state()["move_ids"]
            if row["id"] == move.id
        ]
        self.assertEqual(len(rows), 3)
        rows_by_package = {row["package_name"]: row for row in rows}
        for package_name, expected_qty in (
            ("PKG-SCAN-A", 2.0),
            ("PKG-SCAN-B", 3.0),
            ("", 2.0),
        ):
            self.assertEqual(
                rows_by_package[package_name]["lots"][0]["picked_quantity"],
                expected_qty,
            )

    def test_scan_same_lot_updates_only_existing_unpacked_line(self):
        """When packed and unpacked rows coexist, only the unpacked row grows."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-PACKED-AND-UNPACKED")
        package = self.env["stock.package"].create({"name": "PKG-SEALED-4"})
        packed = self._create_picked_lot_line(
            picking, lot, 4.0, package=package
        )
        unpacked = self._create_picked_lot_line(picking, lot, 2.0)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(packed.quantity, 4.0)
        self.assertEqual(packed.result_package_id, package)
        self.assertEqual(unpacked.quantity, 3.0)
        self.assertFalse(unpacked.result_package_id)

    def test_scan_state_repeated_lot_delta_identifies_unpacked_row(self):
        """A repeated lot scan exposes one positive delta for UI highlighting."""
        picking = self._create_in_picking(self.product_lot, qty=20.0)
        lot = self._create_lot(self.product_lot, "TR-HIGHLIGHT-REPEAT")
        package = self.env["stock.package"].create({"name": "PKG-HIGHLIGHT"})
        self._create_picked_lot_line(picking, lot, 1.0, package=package)
        self._create_picked_lot_line(picking, lot, 10.0)
        wiz = self._create_wiz(picking)

        before = wiz.get_scan_state()["move_ids"]
        result = wiz.process_barcode_and_dispatch(lot.name)
        after = result["state"]["move_ids"]

        def picked_quantities(rows):
            return {
                (row["row_key"], lot_state["id"]): lot_state["picked_quantity"]
                for row in rows
                for lot_state in row["lots"]
                if lot_state["picked"]
            }

        before_qty = picked_quantities(before)
        after_qty = picked_quantities(after)
        increased = [
            (row_key, lot_id, before_qty.get((row_key, lot_id), 0.0), quantity)
            for (row_key, lot_id), quantity in after_qty.items()
            if quantity > before_qty.get((row_key, lot_id), 0.0)
        ]
        unpacked_row_key = next(
            row["row_key"] for row in before if not row["package_id"]
        )
        self.assertEqual(
            increased,
            [(unpacked_row_key, lot.id, 10.0, 11.0)],
        )
        packed_row = next(row for row in after if row["package_id"] == package.id)
        self.assertEqual(packed_row["lots"][0]["picked_quantity"], 1.0)

    def test_scan_new_lot_allow_never_redistributes_packed_quantity(self):
        """Allowed over-picking cannot take quantity from a sealed package."""
        picking = self._create_in_picking(self.product_lot, qty=5.0)
        picking.picking_type_id.barcode_excess_qty_policy = "allow"
        lot_a = self._create_lot(self.product_lot, "TR-PACKED-CAPACITY-A")
        lot_b = self._create_lot(self.product_lot, "TR-PACKED-CAPACITY-B")
        package = self.env["stock.package"].create({"name": "PKG-CAPACITY-ALLOW"})
        packed = self._create_picked_lot_line(
            picking, lot_a, 5.0, package=package
        )
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot_b.name)

        unpacked_b = picking.move_line_ids.filtered(
            lambda l: l.lot_id == lot_b and l.picked and not l.result_package_id
        )
        self.assertEqual(len(unpacked_b), 1)
        self.assertEqual(unpacked_b.quantity, 1.0)
        self.assertEqual(packed.quantity, 5.0)
        self.assertEqual(packed.result_package_id, package)

    def test_scan_new_lot_warn_preserves_package_before_and_after_force(self):
        """Warn confirmation preserves the package on both scan attempts."""
        picking = self._create_in_picking(self.product_lot, qty=5.0)
        picking.picking_type_id.barcode_excess_qty_policy = "warn"
        lot_a = self._create_lot(self.product_lot, "TR-PACKED-WARN-A")
        lot_b = self._create_lot(self.product_lot, "TR-PACKED-WARN-B")
        package = self.env["stock.package"].create({"name": "PKG-CAPACITY-WARN"})
        packed = self._create_picked_lot_line(
            picking, lot_a, 5.0, package=package
        )
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot_b.name)

        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_done)
        self.assertFalse(picking.move_line_ids.filtered(lambda l: l.lot_id == lot_b))
        self.assertEqual(packed.quantity, 5.0)
        self.assertTrue(wiz.action_force_done())
        unpacked_b = picking.move_line_ids.filtered(
            lambda l: l.lot_id == lot_b and l.picked and not l.result_package_id
        )
        self.assertEqual(len(unpacked_b), 1)
        self.assertEqual(unpacked_b.quantity, 1.0)
        self.assertEqual(packed.quantity, 5.0)
        self.assertEqual(packed.result_package_id, package)

    def test_scan_new_lot_forbid_preserves_package_even_with_force(self):
        """Forbidden over-picking rejects both scan and forced confirmation."""
        picking = self._create_in_picking(self.product_lot, qty=5.0)
        picking.picking_type_id.barcode_excess_qty_policy = "forbid"
        lot_a = self._create_lot(self.product_lot, "TR-PACKED-FORBID-A")
        lot_b = self._create_lot(self.product_lot, "TR-PACKED-FORBID-B")
        package = self.env["stock.package"].create({"name": "PKG-CAPACITY-FORBID"})
        packed = self._create_picked_lot_line(
            picking, lot_a, 5.0, package=package
        )
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot_b.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertFalse(wiz.action_force_done())
        self.assertFalse(picking.move_line_ids.filtered(lambda l: l.lot_id == lot_b))
        self.assertEqual(packed.quantity, 5.0)
        self.assertEqual(packed.result_package_id, package)

    def test_scan_new_serial_after_packing_creates_unpacked_line(self):
        """A new SN is picked as unpacked while the packed SN stays sealed."""
        product = self._create_serial_product(
            "Packed Serial Scan", "PROD-PACKED-SERIAL-SCAN"
        )
        picking = self._create_in_picking(product, qty=3.0)
        packed_lot = self._create_lot(product, "SN-PACKED-SEALED")
        new_lot = self._create_lot(product, "SN-PACKED-NEW")
        package = self.env["stock.package"].create({"name": "PKG-SERIAL-SEALED"})
        packed = self._create_picked_lot_line(
            picking, packed_lot, 1.0, package=package
        )
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(new_lot.name)

        new_line = picking.move_line_ids.filtered(
            lambda l: l.lot_id == new_lot and l.picked and not l.result_package_id
        )
        self.assertEqual(len(new_line), 1)
        self.assertEqual(new_line.quantity, 1.0)
        self.assertEqual(packed.quantity, 1.0)
        self.assertEqual(packed.result_package_id, package)

    # --- New lot uniqueness ---
    def test_create_new_lot_search_then_create(self):
        """Scanning an unknown barcode creates a lot; scanning the same
        barcode again reuses it (search-then-create, no duplicate)."""
        picking = self._create_picking(self.product_lot, qty=10.0)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        wiz.on_barcode_scanned("LOT-UNIQUE-001")
        lot_1 = self.env["stock.lot"].search([
            ("name", "=", "LOT-UNIQUE-001"),
            ("product_id", "=", self.product_lot.id),
        ])
        self.assertTrue(lot_1, "the first scan should create and pick the lot")

        # Scan same lot barcode again: reuse the record and pick one more.
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(self.product_lot.barcode)
        wiz.on_barcode_scanned("LOT-UNIQUE-001")
        count = self.env["stock.lot"].search_count([
            ("name", "=", "LOT-UNIQUE-001"),
            ("product_id", "=", self.product_lot.id),
        ])
        self.assertEqual(count, 1)
        line = picking.move_line_ids.filtered(lambda l: l.lot_id == lot_1)
        self.assertEqual(line.quantity, 2.0)
        self.assertTrue(line.picked)

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

    def test_scan_return_serial_from_destination_rejected(self):
        """A customer return rejects a serial that is still in stock."""
        product = self._create_serial_product(
            "Return Serial Elsewhere", "PROD-SN-RETURN-ELSEWHERE"
        )
        lot = self._create_lot(product, "SN-RETURN-ELSEWHERE-001")
        original = self._create_out_picking(product)
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_in_picking(product, return_of=original)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(product.barcode)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("not in location", wiz.message)
        self.assertIn(self.customer_location.display_name, wiz.message)
        self.assertIn(self.stock_location.display_name, wiz.message)
        self.assertFalse(
            picking.move_line_ids.filtered(lambda l: l.lot_id == lot),
            "the serial must not be added to the customer return",
        )

    def test_scan_return_serial_from_customer_allowed(self):
        """A customer return accepts its serial at the customer source."""
        product = self._create_serial_product(
            "Return Serial Valid", "PROD-SN-RETURN-VALID"
        )
        lot = self._create_lot(product, "SN-RETURN-VALID-001")
        original = self._create_out_picking(product)
        self.StockQuant._update_available_quantity(
            product, self.customer_location, 1.0, lot_id=lot
        )
        picking = self._create_in_picking(product, return_of=original)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        line = picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(line), 1)
        self.assertTrue(line.picked)
        self.assertEqual(line.quantity, 1.0)

    def test_scan_receipt_existing_serial_needs_no_vendor_stock(self):
        """A regular supplier receipt keeps the source-stock exemption."""
        product = self._create_serial_product(
            "Receipt Existing Serial", "PROD-SN-RECEIPT-EXISTING"
        )
        lot = self._create_lot(product, "SN-RECEIPT-EXISTING-001")
        picking = self._create_in_picking(product)
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        line = picking.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(line), 1)
        self.assertTrue(line.picked)
        self.assertEqual(line.quantity, 1.0)

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

    # --- outside-product serial policy ---
    def test_new_product_allow_creates_move_and_picks_serial(self):
        """Allow adds one demanded unit and picks the scanned serial."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("allow")
        before = len(picking.move_ids)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        self.assertEqual(len(picking.move_ids), before + 1)
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(len(move), 1)
        self.assertEqual(move.product_uom_qty, 1.0)
        line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.quantity, 1.0)
        self.assertTrue(line.picked)
        self.assertEqual(wiz.active_move_id, move)
        self.assertNotEqual(picking.state, "done")

    def test_new_product_warn_writes_only_after_confirmation(self):
        """Warn prepares the scan but creates no business records upfront."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("warn")
        before = len(picking.move_ids)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_add)
        self.assertEqual(wiz.product_id, product)
        self.assertEqual(wiz.lot_id, lot)
        self.assertEqual(len(picking.move_ids), before)
        self.assertFalse(picking.move_line_ids.filtered(lambda l: l.lot_id == lot))

        self.assertTrue(wiz.action_confirm_new_product())
        self.assertFalse(wiz.visible_force_add)
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(move.product_uom_qty, 1.0)
        line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertTrue(line.picked)
        self.assertEqual(line.quantity, 1.0)

    def test_new_product_warn_cancel_leaves_picking_unchanged(self):
        """Cancelling the warning clears only the wizard scan context."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("warn")
        before_moves = picking.move_ids
        before_lines = picking.move_line_ids
        wiz.on_barcode_scanned(lot.name)

        self.assertTrue(wiz.action_cancel_new_product())

        self.assertFalse(wiz.visible_force_add)
        self.assertFalse(wiz.product_id)
        self.assertFalse(wiz.lot_id)
        self.assertEqual(picking.move_ids, before_moves)
        self.assertEqual(picking.move_line_ids, before_lines)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_warn_rechecks_stock_on_confirmation(self):
        """Confirmation revalidates stock instead of trusting the preview."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("warn")
        wiz.on_barcode_scanned(lot.name)
        self.StockQuant._update_available_quantity(
            product, self.stock_location, -1.0, lot_id=lot
        )

        self.assertFalse(wiz.action_confirm_new_product())

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("no stock", wiz.message)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_allow_rejects_serial_in_other_location(self):
        """The outside-product flow keeps the source-location safety check."""
        other_location = self.StockLocation.create({
            "name": "Outside Serial Stock",
            "usage": "internal",
            "location_id": self.warehouse.view_location_id.id,
        })
        product, lot, picking, wiz = self._prepare_outside_serial_scan(
            "allow", location=other_location
        )

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn(other_location.display_name, wiz.message)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_allow_rejects_serial_reserved_elsewhere(self):
        """An outside serial reserved by another transfer is not added."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("allow")
        other_picking = self._create_out_picking(product)
        self.assertTrue(other_picking.move_line_ids.filtered(lambda l: l.lot_id == lot))

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("reserved by another transfer", wiz.message)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_allow_serial_overrides_selected_product(self):
        """A unique outside serial supersedes product A's pending input."""
        self.picking_type.barcode_new_product_policy = "allow"
        selected = self._create_serial_product(
            "Selected Serial", "PROD-SELECTED-SERIAL"
        )
        outside = self._create_serial_product(
            "Other Selected Serial", "PROD-OTHER-SELECTED-SERIAL"
        )
        lot = self._create_lot(outside, "SN-OTHER-SELECTED-001")
        self.StockQuant._update_available_quantity(
            outside, self.stock_location, 1.0, lot_id=lot
        )
        picking = self._create_out_picking(selected)
        selected_move = picking.move_ids
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)
        wiz.on_barcode_scanned(selected.barcode)
        wiz.lot_name = "SN-PENDING-A"
        wiz.product_qty = 1.0

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        outside_move = picking.move_ids.filtered(lambda m: m.product_id == outside)
        self.assertEqual(len(outside_move), 1)
        self.assertEqual(outside_move.product_uom_qty, 1.0)
        self.assertTrue(
            outside_move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        )
        self.assertEqual(wiz.active_move_id, outside_move)
        self.assertFalse(selected_move.move_line_ids)
        self.assertFalse(wiz.lot_name)

    def test_new_product_warn_serial_overrides_nontracked_pending_qty(self):
        """Warn also applies when a non-tracked product has a pending qty."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("warn")
        selected_move = picking.move_ids
        wiz.product_id = self.product_simple
        wiz.active_move_id = selected_move
        wiz.product_qty = 5.0
        before_moves = picking.move_ids

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_add)
        self.assertEqual(wiz.product_id, product)
        self.assertEqual(wiz.product_qty, 1.0)
        self.assertFalse(wiz.active_move_id)
        self.assertEqual(picking.move_ids, before_moves)
        self.assertTrue(wiz.action_confirm_new_product())
        self.assertEqual(
            picking.move_ids.filtered(
                lambda m: m.product_id == product
            ).product_uom_qty,
            1.0,
        )

    def test_new_product_forbid_preserves_selected_product_context(self):
        """Forbid rejects the serial without discarding product A's input."""
        product, lot, picking, wiz = self._prepare_outside_serial_scan("forbid")
        selected_move = picking.move_ids
        wiz.product_id = self.product_simple
        wiz.active_move_id = selected_move
        wiz.product_qty = 5.0

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("not part of this transfer", wiz.message)
        self.assertEqual(wiz.product_id, self.product_simple)
        self.assertEqual(wiz.active_move_id, selected_move)
        self.assertEqual(wiz.product_qty, 5.0)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_then_excess_policy_controls_next_serial(self):
        """After the first add, further serials use the excess policy."""
        self.picking_type.barcode_excess_qty_policy = "forbid"
        product, lot_1, picking, wiz = self._prepare_outside_serial_scan("allow")
        lot_2 = self._create_lot(product, "SN-OUTSIDE-002")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 1.0, lot_id=lot_2
        )
        wiz.on_barcode_scanned(lot_1.name)
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(move.product_uom_qty, 1.0)

        wiz.on_barcode_scanned(lot_2.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("forbidden", wiz.message)
        self.assertFalse(move.move_line_ids.filtered(lambda l: l.lot_id == lot_2))
        self.assertEqual(move.product_uom_qty, 1.0)

    def test_new_product_allow_does_not_create_from_unknown_barcode(self):
        """An unknown barcode cannot infer or auto-create a product."""
        self.picking_type.barcode_new_product_policy = "allow"
        picking = self._create_out_picking(self.product_simple)
        before = len(picking.move_ids)
        wiz = self._create_wiz(picking)
        wiz.on_barcode_scanned(self.stock_location.barcode)

        wiz.on_barcode_scanned("SN-OUTSIDE-UNKNOWN")

        self.assertEqual(wiz.message_type, "error")
        self.assertEqual(len(picking.move_ids), before)
        self.assertFalse(
            self.env["stock.lot"].search([("name", "=", "SN-OUTSIDE-UNKNOWN")])
        )

    def test_new_product_allow_on_receipt_needs_no_vendor_stock(self):
        """Incoming outside serials keep the receipt stock-check exemption."""
        receipt_type = self.env.ref("stock.picking_type_in")
        receipt_type.barcode_new_product_policy = "allow"
        receipt_type.barcode_scan_source_location = False
        receipt_type.barcode_scan_dest_location = False
        product = self._create_serial_product(
            "Outside Receipt Serial", "PROD-OUTSIDE-RECEIPT"
        )
        lot = self._create_lot(product, "SN-OUTSIDE-RECEIPT-001")
        supplier = self.env.ref("stock.stock_location_suppliers")
        picking = self.StockPicking.create({
            "picking_type_id": receipt_type.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        self.StockMove.create({
            "product_id": self.product_simple.id,
            "product_uom_qty": 1.0,
            "product_uom": self.product_simple.uom_id.id,
            "picking_id": picking.id,
            "location_id": supplier.id,
            "location_dest_id": self.stock_location.id,
        })
        picking.action_confirm()
        wiz = self._create_wiz(picking)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(move.product_uom_qty, 1.0)
        line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertTrue(line.picked)
        self.assertEqual(line.quantity, 1.0)

    # --- outside-product lot policy ---
    def test_new_product_allow_creates_move_and_picks_lot(self):
        """Allow adds one demanded unit and picks the scanned lot."""
        product, lot, picking, wiz = self._prepare_outside_lot_scan("allow")
        before = len(picking.move_ids)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        self.assertEqual(len(picking.move_ids), before + 1)
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(len(move), 1)
        self.assertEqual(move.product_uom_qty, 1.0)
        line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.quantity, 1.0)
        self.assertTrue(line.picked)
        self.assertFalse(line.result_package_id)
        self.assertEqual(wiz.active_move_id, move)

    def test_new_product_warn_lot_writes_only_after_confirmation(self):
        """Warn prepares an outside lot without creating business records."""
        product, lot, picking, wiz = self._prepare_outside_lot_scan("warn")
        before_moves = picking.move_ids
        before_lines = picking.move_line_ids

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "more_match")
        self.assertTrue(wiz.visible_force_add)
        self.assertEqual(wiz.product_id, product)
        self.assertEqual(wiz.lot_id, lot)
        self.assertEqual(wiz.product_qty, 1.0)
        self.assertEqual(picking.move_ids, before_moves)
        self.assertEqual(picking.move_line_ids, before_lines)

        self.assertTrue(wiz.action_confirm_new_product())
        self.assertFalse(wiz.visible_force_add)
        move = picking.move_ids.filtered(lambda m: m.product_id == product)
        self.assertEqual(move.product_uom_qty, 1.0)
        line = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(line.quantity, 1.0)
        self.assertTrue(line.picked)
        self.assertFalse(line.result_package_id)

    def test_new_product_warn_lot_cancel_leaves_picking_unchanged(self):
        """Cancelling an outside-lot preview only clears the wizard."""
        product, lot, picking, wiz = self._prepare_outside_lot_scan("warn")
        before_moves = picking.move_ids
        before_lines = picking.move_line_ids
        wiz.on_barcode_scanned(lot.name)

        self.assertTrue(wiz.action_cancel_new_product())

        self.assertFalse(wiz.visible_force_add)
        self.assertFalse(wiz.product_id)
        self.assertFalse(wiz.lot_id)
        self.assertEqual(picking.move_ids, before_moves)
        self.assertEqual(picking.move_line_ids, before_lines)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_warn_lot_rechecks_stock_on_confirmation(self):
        """Outside-lot confirmation revalidates the source stock."""
        product, lot, picking, wiz = self._prepare_outside_lot_scan(
            "warn", quantity=1.0
        )
        wiz.on_barcode_scanned(lot.name)
        self.StockQuant._update_available_quantity(
            product, self.stock_location, -1.0, lot_id=lot
        )

        self.assertFalse(wiz.action_confirm_new_product())

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("no stock", wiz.message)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_forbid_lot_preserves_selected_product_context(self):
        """Forbid rejects an outside lot without discarding pending input."""
        product, lot, picking, wiz = self._prepare_outside_lot_scan("forbid")
        selected_move = picking.move_ids
        wiz.product_id = self.product_simple
        wiz.active_move_id = selected_move
        wiz.product_qty = 5.0

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "error")
        self.assertIn("not part of this transfer", wiz.message)
        self.assertFalse(wiz.visible_force_add)
        self.assertEqual(wiz.product_id, self.product_simple)
        self.assertEqual(wiz.active_move_id, selected_move)
        self.assertEqual(wiz.product_qty, 5.0)
        self.assertFalse(picking.move_ids.filtered(lambda m: m.product_id == product))

    def test_new_product_lot_then_excess_policy_controls_next_scan(self):
        """After confirmation, the same lot uses normal accumulation rules."""
        self.picking_type.barcode_excess_qty_policy = "allow"
        product, lot, picking, wiz = self._prepare_outside_lot_scan("warn")
        wiz.on_barcode_scanned(lot.name)
        self.assertTrue(wiz.action_confirm_new_product())
        move = picking.move_ids.filtered(lambda m: m.product_id == product)

        wiz.on_barcode_scanned(lot.name)

        self.assertEqual(wiz.message_type, "success")
        self.assertEqual(move.product_uom_qty, 1.0)
        lines = move.move_line_ids.filtered(lambda l: l.lot_id == lot)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines.quantity, 2.0)
        self.assertTrue(lines.picked)
        self.assertFalse(lines.result_package_id)

    def test_new_product_second_lot_preserves_first_when_excess_allowed(self):
        """Allowed over-picking adds a different lot without replacing others."""
        self.picking_type.barcode_excess_qty_policy = "allow"
        product, lot_1, picking, wiz = self._prepare_outside_lot_scan("warn")
        lot_2 = self._create_lot(product, "LOT-OUTSIDE-002")
        self.StockQuant._update_available_quantity(
            product, self.stock_location, 10.0, lot_id=lot_2
        )
        wiz.on_barcode_scanned(lot_1.name)
        self.assertTrue(wiz.action_confirm_new_product())
        move = picking.move_ids.filtered(lambda m: m.product_id == product)

        wiz.on_barcode_scanned(lot_2.name)

        self.assertEqual(wiz.message_type, "success")
        self.assertEqual(move.product_uom_qty, 1.0)
        lines = move.move_line_ids.filtered(lambda l: l.lot_id in (lot_1 | lot_2))
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            {line.lot_id.name: line.quantity for line in lines},
            {lot_1.name: 1.0, lot_2.name: 1.0},
        )
        self.assertTrue(all(lines.mapped("picked")))
        self.assertFalse(any(lines.mapped("result_package_id")))

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
