# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models

from odoo.tools.float_utils import float_compare, float_is_zero


class WizStockBarcodesPicking(models.TransientModel):
    _name = "wiz.stock.barcodes.picking"
    _inherit = "barcodes.barcode_events_mixin"
    _description = "Wizard to read barcode on pickings"
    _transient_max_hours = 48

    # --- Picking context ---
    # NB: NOT field-level readonly. Readonly fields are dropped from the
    # client save payload, so a hardware/manual scan landing on a *new*
    # onchange RPC would browse a record with picking_id=False and every
    # cross-request scan step would fall through ("Barcode not found").
    picking_id = fields.Many2one(
        comodel_name="stock.picking",
        string="Transfer",
    )
    picking_state = fields.Selection(related="picking_id.state")
    picking_type_code = fields.Selection(related="picking_id.picking_type_code")
    picking_location_id = fields.Many2one(
        comodel_name="stock.location",
        related="picking_id.location_id",
        string="Picking Source Location",
        help="Static: the picking's own source location, bound when "
             "picking_id is set. Never overwritten by scanning.",
    )
    picking_location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        related="picking_id.location_dest_id",
        string="Destination Location",
        help="Static: the picking's destination location.",
    )
    company_id = fields.Many2one(related="picking_id.company_id")

    # --- Picking-type barcode configuration ---
    barcode_scan_source_location = fields.Boolean(
        related="picking_id.picking_type_id.barcode_scan_source_location",
        string="Scan Source Location",
        help="Whether the operator must scan the source location barcode. "
             "When False, the picking's default source location is used.",
    )
    barcode_scan_dest_location = fields.Boolean(
        related="picking_id.picking_type_id.barcode_scan_dest_location",
        string="Scan Destination Location",
        help="Whether the operator must scan the destination location "
             "barcode. When False, the picking's default destination "
             "location is used.",
    )

    # --- Scanned values ---
    barcode = fields.Char()
    res_model_id = fields.Many2one(comodel_name="ir.model", index=True)
    res_id = fields.Integer(index=True)
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Scanned Source Location",
        help="Dynamic: the source location scanned by the operator. "
             "Overrides picking_location_id for the current scan context. "
             "Defaulted to picking_location_id on picking switch.",
    )
    location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        string="Scanned Destination Location",
        help="Dynamic: the destination location scanned by the operator. "
             "Only used when the picking type requires destination "
             "location scanning. Otherwise picking_location_dest_id "
             "is used.",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Product",
    )
    product_uom_id = fields.Many2one(comodel_name="uom.uom", string="UoM")
    product_tracking = fields.Selection(related="product_id.tracking", readonly=True)
    lot_id = fields.Many2one(comodel_name="stock.lot", string="Lot/Serial")
    lot_name = fields.Char(string="Lot Name")
    product_qty = fields.Float(
        string="Quantity", digits="Product Unit of Measure"
    )
    manual_entry = fields.Boolean(
        string="Manual", help="Manual entry mode",
        default=False,
    )

    # --- Display fields ---
    message_type = fields.Selection(
        [
            ("info", "Info"),
            ("not_found", "Not found"),
            ("more_match", "Multiple matches"),
            ("success", "Success"),
            ("error", "Error"),
        ],
        readonly=True,
    )
    message = fields.Char(readonly=True)
    step = fields.Integer(default=0)
    visible_force_done = fields.Boolean()
    visible_force_add = fields.Boolean(
        string="Force Add",
        help="Show the 'Force Add' button to move a product not in the picking",
    )
    qty_available = fields.Float(
        string="Available", digits="Product Unit of Measure", readonly=True,
    )
    total_demand = fields.Float(
        string="Demand", digits="Product Unit of Measure",
        compute="_compute_totals",
    )
    total_done = fields.Float(
        string="Done", digits="Product Unit of Measure",
        compute="_compute_totals",
    )

    # --- Move checklist (picking.move_ids) ---
    move_ids = fields.One2many(
        related="picking_id.move_ids",
        string="Stock Moves",
        readonly=True,
    )

    # --- Click-to-select target move ---
    active_move_id = fields.Many2one(
        comodel_name="stock.move",
        string="Active Move",
        help="Operator-selected target move. When set, scanning a "
             "serial/lot narrows the lot lookup to this move's product "
             "first, so cross-product SN collisions resolve automatically. "
             "Cleared on picking switch or scanning a different product.",
    )

    # --- Scan-first picking switching ---
    pending_switch_picking_ids = fields.Many2many(
        comodel_name="stock.picking",
        string="Candidate Pickings",
        help="Pickings matching an ambiguous scan; the operator picks one "
             "to switch to.",
    )
    visible_switch_selector = fields.Boolean(
        string="Show Picking Selector",
        help="Display the ambiguous-picking selection list.",
    )
    scan_progress_stash = fields.Json(
        string="Stashed Scan Progress",
    )

    # --- Scan steps ---
    def _get_scan_steps(self):
        """Current picking type's ordered scan steps.

        Steps are built from the picking type's barcode configuration:
          - ``location``      included only if barcode_scan_source_location
          - ``dest_location`` included only if barcode_scan_dest_location
          - ``product``       always
          - ``lot``           always (skipped for non-tracked products
                              inside _scan_product, which jumps to qty)
          - ``qty``           always

        Both location steps (when enabled) come BEFORE product so that
        move lines are created with the correct source/destination
        locations from the first pick.

        When a step is absent from this list, _step_index(key) asserts;
        callers must guard on the config flags before referencing a
        conditional step.
        """
        self.ensure_one()
        steps = []
        if self.barcode_scan_source_location:
            steps.append("location")
        if self.barcode_scan_dest_location:
            steps.append("dest_location")
        steps.extend(["product", "lot", "qty"])
        return steps

    # --- Message state machine ---
    def _set_message(self, message_type, message):
        self.message_type = message_type
        self.message = message

    def _get_step_message(self):
        """Context-aware scan instruction for the current step.

        Always states WHAT to scan next and for which product/picking, so
        the text stays meaningful after a progress restore
        (_restore_progress re-runs _set_message_step and the banner
        reflects the restored step automatically).
        """
        self.ensure_one()
        target_product = self.product_id or (
            self.active_move_id.product_id if self.active_move_id else False
        )
        steps = self._get_scan_steps()
        if self.step < 0 or self.step >= len(steps):
            return ""
        step_key = steps[self.step]
        if step_key == "location":
            return _("Scan the source location of transfer %s") % (
                self.picking_id.name or ""
            )
        if step_key == "product":
            return _("Scan a product of transfer %s") % (
                self.picking_id.name or ""
            )
        if step_key == "lot":
            if not target_product:
                return _("Scan a product barcode first")
            return _("Scan the lot/serial of %s") % target_product.name
        if step_key == "qty":
            if not target_product:
                return _("Scan a product barcode first")
            return _("Enter the quantity for %s") % target_product.name
        if step_key == "dest_location":
            return _("Scan the destination location of transfer %s") % (
                self.picking_id.name or ""
            )
        return ""

    def _set_message_step(self):
        # Dynamic instruction for the banner (driven by the scan-flow
        # `step` state machine).
        self._set_message("info", self._get_step_message())

    # --- Totals ---
    @api.depends("picking_id")
    def _compute_totals(self):
        """Picking-wide progress: total demand vs picked quantity.

        Computed over ALL moves of the picking (not just the currently
        scanned product) so the progress bar stays meaningful after a
        serial auto-confirm clears product_id. Only picked move lines
        count toward ``total_done`` — reserved-but-unpicked lines do
        not, otherwise an assigned picking would show 100% before any
        scan.
        """
        for rec in self:
            rec.total_demand = 0.0
            rec.total_done = 0.0
            if not rec.picking_id:
                continue
            for move in rec.picking_id.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            ):
                rec.total_demand += move.product_uom_qty
                rec.total_done += sum(
                    line.quantity for line in move.move_line_ids if line.picked
                )

    # --- Default values ---
    def _set_default_values(self):
        """Set the wizard to a clean initial state for the current picking.

        Called on picking switch and after a successful move line
        confirmation to advance the step machine.

        The starting step depends on the picking type's barcode
        configuration:
          - source location scanning ON  → start at "location"
          - source location scanning OFF → start at "product" and use
            the picking's default source location automatically.
        """
        self.ensure_one()
        if not self.picking_id:
            self.step = 0
            return
        if self.barcode_scan_source_location:
            self.step = self._step_index("location")
            # location_id stays False — the operator MUST scan the source
            # location. action_confirm's "not location_id → error" check
            # enforces this.
            self.location_id = False
        else:
            # Skip the source-location step: use the picking's default
            # source location directly.
            self.location_id = self.picking_location_id
        if not self.barcode_scan_dest_location:
            # Use the picking's default destination location.
            self.location_dest_id = self.picking_location_dest_id
        # Step lands on the first required location step, or "product"
        # when both location scans are disabled.
        steps = self._get_scan_steps()
        self.step = 0
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self._set_message_step()

    # --- Picking switch with stash/restore ---
    def _stash_current_progress(self):
        """Snapshot the uncommitted scan state of the current picking.

        Restored (and consumed) by ``_restore_progress`` when the operator
        switches back. Only pickings with an in-progress scan (product or
        lot already scanned) are stashed.
        """
        self.ensure_one()
        picking = self.picking_id
        if not picking or not (self.product_id or self.lot_id):
            return
        stash = dict(self.scan_progress_stash or {})
        stash[str(picking.id)] = {
            "product_id": self.product_id.id if self.product_id else False,
            "product_uom_id": (
                self.product_uom_id.id if self.product_uom_id else False
            ),
            "lot_id": self.lot_id.id if self.lot_id else False,
            "lot_name": self.lot_name,
            "product_qty": self.product_qty,
            "location_id": self.location_id.id if self.location_id else False,
            "location_dest_id": (
                self.location_dest_id.id if self.location_dest_id else False
            ),
            "active_move_id": (
                self.active_move_id.id if self.active_move_id else False
            ),
            "step": self.step,
            "visible_force_done": self.visible_force_done,
            "visible_force_add": self.visible_force_add,
        }
        self.scan_progress_stash = stash

    def _restore_progress(self, picking):
        """Restore uncommitted scan state stashed for ``picking``.

        The stash entry is consumed (deleted) on restore. Returns True when
        a snapshot was restored, False when there was none.

        For picking, step 0 = location is a valid step, so we do NOT coerce
        it (unlike mrp's step-0-is-finished-lot pattern).
        """
        self.ensure_one()
        stash = dict(self.scan_progress_stash or {})
        snapshot = stash.pop(str(picking.id), None)
        if not snapshot:
            return False
        self.scan_progress_stash = stash
        self.product_id = snapshot.get("product_id") or False
        self.product_uom_id = snapshot.get("product_uom_id") or False
        self.lot_id = snapshot.get("lot_id") or False
        self.lot_name = snapshot.get("lot_name") or False
        self.product_qty = snapshot.get("product_qty") or 0.0
        self.location_id = snapshot.get("location_id") or False
        self.location_dest_id = snapshot.get("location_dest_id") or False
        self.active_move_id = snapshot.get("active_move_id") or False
        self.visible_force_done = bool(snapshot.get("visible_force_done"))
        self.visible_force_add = bool(snapshot.get("visible_force_add"))
        # step 0 may be "location" or "product" depending on the picking
        # type config — do not coerce. Fall back to the first step of the
        # current picking type's step list (safe even when the source
        # location step is disabled).
        step = snapshot.get("step")
        self.step = step if step is not None else 0
        if self.product_id:
            self._compute_qty_available()
        self._set_message_step()
        return True

    def _switch_picking(self, new_picking):
        """Switch the wizard to ``new_picking``, resetting scan context.

        Call order (enforced here, not by callers):
          1. ``_stash_current_progress`` — snapshot the OLD picking's
             in-progress scan before we overwrite any state.
          2. reset all scan fields to defaults.
          3. ``_restore_progress(new_picking)`` — restore the NEW
             picking's stashed scan if any; otherwise fall back to
             ``_set_default_values`` (fresh start from location step).

        location_id is reset to False during step 2 and may be restored
        by ``_restore_progress`` (if the operator had already scanned the
        source location for this picking). ``_set_default_values`` does
        NOT set location_id, so a fresh picking starts at the location
        step and the operator must scan.
        """
        self.ensure_one()
        # 1. Stash the old picking's progress (must run BEFORE any field
        #    is overwritten so the snapshot reflects the live state).
        if self.picking_id and self.picking_id != new_picking:
            self._stash_current_progress()
        # 2. Reset scan context
        self.picking_id = new_picking
        self.product_id = False
        self.product_uom_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.location_id = False
        self.location_dest_id = False
        self.active_move_id = False
        self.visible_force_done = False
        self.visible_force_add = False
        self.barcode = False
        self.res_model_id = self.env.ref("stock.model_stock_picking").id
        self.res_id = new_picking.id
        self.pending_switch_picking_ids = [(5, 0, 0)]
        self.visible_switch_selector = False
        # 3. Restore stashed progress for the new picking, or start fresh
        if not self._restore_progress(new_picking):
            self._set_default_values()
        self._set_message(
            "info",
            _("Switched to transfer %(picking)s. %(next)s")
            % {"picking": new_picking.name, "next": self.message},
        )

    def select_picking_candidate(self, picking_id):
        """User picks one of the candidate pickings from the selector.

        Validates the picked id is among the pending candidates, then
        switches to it (which closes the selector and clears candidates).
        """
        self.ensure_one()
        candidates = self.pending_switch_picking_ids
        picked = candidates.filtered(lambda p: p.id == picking_id)
        if not picked:
            self._set_message(
                "error",
                _("Selected transfer is not in the candidate list"),
            )
            return False
        self._switch_picking(picked)
        return True

    # --- State snapshot for the OWL client ---
    def get_scan_state(self):
        """JSON-serializable snapshot of the wizard state for the OWL
        client action to render.
        """
        self.ensure_one()
        picking = self.picking_id
        # Step labels are built here (not as a class attribute) so _() is
        # evaluated at request time under the correct lang context. Unknown
        # keys fall back to the raw key string (no default label) so a
        # missing mapping is visible in the UI instead of silently wrong.
        step_labels = {
            "location": _("库位"),
            "product": _("产品"),
            "lot": _("批次"),
            "qty": _("数量"),
            "dest_location": _("目的库位"),
        }
        scan_steps = [
            {"key": k, "label": step_labels.get(k, k)}
            for k in self._get_scan_steps()
        ]
        show_reserved = bool(
            picking.picking_type_id.barcode_show_reserved_sns
        )
        moves = []
        for mv in self.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        ):
            move_lines = mv.move_line_ids
            picked_all = bool(move_lines) and all(l.picked for l in move_lines)
            picked_lines = move_lines.filtered(lambda l: l.picked).sorted(key=lambda l: l.id)
            # Picked lots (always shown)
            lots = [
                {
                    "id": l.lot_id.id,
                    "name": l.lot_id.name,
                    "picked": True,
                    "result_package_name": l.result_package_id.name or "",
                }
                for l in picked_lines
                if l.lot_id
            ]
            # Reserved (unpicked) lots — shown only when configured
            if show_reserved:
                reserved_lines = move_lines.filtered(
                    lambda l: not l.picked and l.lot_id
                ).sorted(key=lambda l: l.id)
                lots += [
                    {"id": l.lot_id.id, "name": l.lot_id.name, "picked": False}
                    for l in reserved_lines
                ]
            picked_lot_ids = [
                l.lot_id.id for l in picked_lines if l.lot_id
            ]
            # Distinct package names of picked lines (for the package row)
            result_package_names = list(dict.fromkeys(
                l.result_package_id.name
                for l in picked_lines
                if l.result_package_id
            ))
            moves.append({
                "id": mv.id,
                "product_name": mv.product_id.display_name or "",
                "product_uom_qty": mv.product_uom_qty,
                "quantity": sum(picked_lines.mapped("quantity")),
                "picked": picked_all,
                "tracking": mv.product_id.tracking or "none",
                "lots": lots,
                "latest_lot_id": picked_lot_ids[-1] if picked_lot_ids else False,
                "result_package_names": result_package_names,
            })
        return {
            "wiz_id": self.id,
            "step": self.step,
            "scan_steps": scan_steps,
            "message": self.message or "",
            "message_type": self.message_type or "info",
            "picking_id": picking.id,
            "picking_name": picking.name or "",
            "picking_state": self.picking_state or "",
            "picking_type_code": self.picking_type_code or "",
            "location_id": self.location_id.id or False,
            "location_name": self.location_id.display_name or "",
            "location_dest_id": self.location_dest_id.id or False,
            "location_dest_name": (
                self.location_dest_id.display_name
                or self.picking_location_dest_id.display_name
                or ""
            ),
            "product_id": self.product_id.id or False,
            "product_name": self.product_id.display_name or "",
            "product_tracking": self.product_tracking or "none",
            "product_uom_name": self.product_uom_id.name or "",
            "lot_id": self.lot_id.id or False,
            "lot_name": self.lot_id.display_name or "",
            "product_qty": self.product_qty or 0.0,
            "qty_available": self.qty_available or 0.0,
            "total_demand": self.total_demand or 0.0,
            "total_done": self.total_done or 0.0,
            "visible_force_done": bool(self.visible_force_done),
            "visible_force_add": bool(self.visible_force_add),
            "visible_switch_selector": bool(self.visible_switch_selector),
            "pending_switch_pickings": [
                {"id": p.id, "name": p.name}
                for p in self.pending_switch_picking_ids
            ],
            "active_move_id": self.active_move_id.id or False,
            "active_move_product_name": (
                self.active_move_id.product_id.display_name or ""
                if self.active_move_id else ""
            ),
            "move_ids": moves,
            # Packaging config
            "show_put_in_pack": self.env.user.has_group("stock.group_tracking_lot"),
            "pack_required": picking.picking_type_id.barcode_require_pack == "mandatory",
            "lines_need_pack": self._lines_need_pack(picking),
        }

    def _lines_need_pack(self, picking):
        """Whether validation requires all picked lines to be packed."""
        pt = picking.picking_type_id
        require = pt.barcode_require_pack
        if require == "mandatory":
            return True
        if require == "optional" and pt.barcode_validation_all_packed:
            return True
        return False

    # --- Step index helper (方案 C 扩展点) ---
    def _step_index(self, key):
        """Return the list index of step ``key`` in ``_get_scan_steps()``.

        Uses assert so a typo'd key fails loud in development instead of
        silently falling back to step 0 (which would mask routing bugs).
        Normal call paths always pass a key present in the current
        picking type's step list.
        """
        self.ensure_one()
        steps = self._get_scan_steps()
        assert key in steps, (
            "step key %r not in %r — check _get_scan_steps()" % (key, steps)
        )
        return steps.index(key)

    # --- Barcode entry points ---
    def on_barcode_scanned(self, barcode):
        """Hardware path: core barcode_handler widget writes
        ``_barcode_scanned`` → core mixin onchange calls this. Processes
        directly and deliberately does NOT write ``barcode``, so the
        client-side onchange chain can never double-fire the manual
        entry handler below.
        """
        self._process_barcode(barcode.strip() if barcode else "")

    @api.onchange("barcode")
    def _onchange_barcode_scan(self):
        """Manual scan box path: the visible ``barcode`` char field is
        the scan entry for tablets/browsers without a hardware scanner.
        Clears the value so the same code can be scanned twice in a row.
        """
        if self.barcode:
            barcode = self.barcode
            self.barcode = False
            self._barcode_scanned = False
            self._process_barcode(barcode)
        # onchange methods must return None or a dict.

    # --- Dispatch chain ---
    def _process_barcode(self, barcode):
        """Main barcode dispatch: picking → location → product → lot.

        Each scanner returns True when it claims the barcode, False to
        let the next scanner try (penetration rule). The only exception
        is a barcode that is clearly a picking name but the picking is
        not in a scannable state — that returns True with an error.
        """
        if not barcode:
            return
        # While the candidate-picking selector is open, only picking-name
        # scans are allowed. Blocking product/lot scans here prevents an
        # ambiguous picking scan from silently writing into the current
        # (possibly wrong) picking.
        if self.visible_switch_selector:
            if not self._scan_picking(barcode):
                self._set_message(
                    "error",
                    _("Select a transfer or scan a transfer name to continue"),
                )
            return True
        if self._scan_picking(barcode):
            return True
        if self._scan_location(barcode):
            return True
        if self._scan_dest_location(barcode):
            return True
        if self._scan_product(barcode):
            return True
        if self._scan_lot(barcode):
            return True
        self._set_message("not_found", _("Barcode not found: %s") % barcode)
        return True

    def _check_selector_resolved(self):
        """Server-side guard: reject write actions while the candidate-
        picking selector is open.

        When ``_scan_picking`` hits a multi-match, ``picking_id`` still
        points at the OLD picking and the selector is open. The
        ``_process_barcode`` guard blocks barcode scans, but action RPCs
        (consume, validate, force-add) would still write to the old
        picking. This shared guard enforces resolution at the entry of
        every action that mutates picking data. Returns True if clear,
        False (with error message) if the selector is still open.
        """
        self.ensure_one()
        if self.visible_switch_selector:
            self._set_message(
                "error",
                _("Select a transfer first before continuing"),
            )
            return False
        return True

    def process_barcode_and_dispatch(self, barcode):
        """One-shot RPC entry for the OWL PickingScanApp client action.

        Runs ``_process_barcode`` then returns ``{action, state}`` where
        ``action`` is None or an act_window dict (e.g. backorder wizard
        from action_validate_picking, or candidate-picking selector).
        ``state`` is the JSON-serializable wizard snapshot.
        """
        self.ensure_one()
        self._process_barcode(barcode)
        return {
            "action": None,
            "state": self.get_scan_state(),
        }

    # --- Scanners ---
    def _scan_picking(self, barcode):
        """Scan-first picking switching by picking reference (name).

        Matches picking.name exactly. Inactive pickings (draft/done/
        cancel) error out without falling through. Single active match
        switches directly; multi-match is out of scope for outgoing
        (no ambiguous selector yet).
        """
        self.ensure_one()
        active_states = ("confirmed", "assigned", "partially_available")
        pickings = self.env["stock.picking"].search([
            ("name", "=", barcode),
            ("state", "in", active_states),
        ])
        if not pickings:
            if self.env["stock.picking"].search_count(
                [("name", "=", barcode)], limit=1
            ):
                self._set_message(
                    "error",
                    _("Transfer %s is not active (draft/done/cancelled)")
                    % barcode,
                )
                return True
            return False
        if len(pickings) > 1:
            # Multiple active pickings share this name. Populate the
            # candidate selector and open it. The dispatch guard below
            # blocks product/lot scans until the user picks one, so an
            # ambiguous scan can never write to the wrong picking.
            self.pending_switch_picking_ids = [(6, 0, pickings.ids)]
            self.visible_switch_selector = True
            self._set_message(
                "more_match",
                _("Multiple transfers found for barcode: %s. Select one.")
                % barcode,
            )
            return True
        picking = pickings
        if self.picking_id == picking:
            self._set_message("info", _("Already on transfer %s") % picking.name)
            return True
        self._switch_picking(picking)
        return True

    def _scan_location(self, barcode):
        # Only internal (physical stock) locations are valid source
        # locations for picking. Customer/supplier/virtual locations are
        # rejected with a distinct message so the operator knows whether
        # the barcode is wrong or the location type is wrong.
        any_location = self.env["stock.location"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not any_location:
            return False
        if any_location.usage != "internal":
            self._set_message(
                "error",
                _("%s is not a stock location (only internal locations "
                  "can be scanned)") % any_location.name,
            )
            return True
        location = any_location
        self.location_id = location
        # Advance to the next step (dest_location if required, else
        # product). Using step+1 instead of a hardcoded step key keeps
        # the flow correct regardless of the picking type config.
        self.step += 1
        self._set_message_step()
        return True

    def _scan_dest_location(self, barcode):
        """Scan the destination location.

        Only triggered when the picking type has
        ``barcode_scan_dest_location`` enabled. Internal locations are
        accepted (the destination of an internal transfer is a stock
        location); customer/supplier locations are also accepted for
        outgoing/incoming pickings.
        """
        any_location = self.env["stock.location"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not any_location:
            return False
        # For destination, accept internal, customer, and supplier
        # locations (outgoing → customer, incoming → supplier,
        # internal → internal). Reject only virtual/inventory/scrap.
        if any_location.usage in ("view", "inventory", "production"):
            self._set_message(
                "error",
                _("%s is not a valid destination location")
                % any_location.name,
            )
            return True
        self.location_dest_id = any_location
        self.step = self._step_index("product")
        self._set_message_step()
        return True

    def _scan_product(self, barcode):
        # type='consu' = Goods (physical products, excludes service/combo).
        # NOTE: do NOT add is_storable=True here. Adding it would EXCLUDE
        # consumables (type='consu' with is_storable=False) that can
        # legitimately appear on a picking — stock.move._should_bypass_
        # reservation skips reservation for them but they still flow
        # through picking. The real admittance gate is the
        # picking.move_ids membership check below.
        domain = [("barcode", "=", barcode), ("type", "=", "consu")]
        products = self.env["product.product"].search(domain)
        if not products:
            return False
        if len(products) > 1:
            self._set_message("more_match", _("Multiple products found"))
            return True
        product = products
        if not self.picking_id:
            self._set_message("error", _("No transfer selected"))
            return True
        # Check the product belongs to this picking's moves
        component_moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if not component_moves:
            self._set_message(
                "error",
                _("Product %(name)s is not part of this transfer")
                % {"name": product.name},
            )
            return True
        self.product_id = product
        if self.active_move_id and self.active_move_id.product_id != product:
            self.active_move_id = False
        self.product_uom_id = product.uom_id
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 1.0
        self._compute_qty_available()
        if product.tracking != "none":
            self._set_message(
                "info", _("Product: %s. Scan lot.") % product.name
            )
            self.step = self._step_index("lot")
        else:
            self._set_message(
                "info",
                _("Product: %s. Enter qty and confirm.") % product.name,
            )
            self.step = self._step_index("qty")
        self._set_message_step()
        return True

    def _scan_lot(self, barcode):
        search_product = self.product_id
        if not search_product and self.active_move_id:
            search_product = self.active_move_id.product_id
        if not search_product or search_product.tracking == "none":
            return False
        lot_domain = [("name", "=", barcode), ("product_id", "=", search_product.id)]
        lots = self.env["stock.lot"].search(lot_domain)
        if not lots:
            return self._scan_lot_fallback(barcode)
        if len(lots) > 1:
            self._set_message("more_match", _("Multiple lots found"))
            return True
        lot = lots
        self.lot_id = lot
        self.lot_name = lot.name
        self.product_id = lot.product_id
        self.product_uom_id = lot.product_id.uom_id
        self._compute_qty_available()
        if self.product_tracking == "serial":
            self.product_qty = 1.0
            # No location fallback: serial auto-confirm will fail in
            # action_confirm ("No source location scanned") until the
            # operator scans the source location.
            self.action_confirm()
            return True
        self._set_message(
            "info", _("Lot: %s. Enter qty and confirm.") % lot.name
        )
        self.step = self._step_index("qty")
        self._set_message_step()
        return True

    def _scan_lot_fallback(self, barcode):
        """The scanned barcode is not a lot of the current product.

        Two-tier lookup before treating it as a new lot:
          1. Global lot name search (company-scoped).
          2. Product barcode search (company-scoped).
        """
        self.ensure_one()
        if not self.picking_id or not self.company_id:
            return self._create_new_lot_flow(barcode)
        lots = self.env["stock.lot"].search([
            ("name", "=", barcode),
            ("company_id", "in", [self.company_id.id, False]),
        ])
        if len(lots) > 1:
            narrowed = lots
            if self.active_move_id:
                narrowed = narrowed.filtered(
                    lambda l: l.product_id == self.active_move_id.product_id
                )
            elif self.product_id:
                narrowed = narrowed.filtered(
                    lambda l: l.product_id == self.product_id
                )
            if len(narrowed) > 1 and self.picking_id:
                picking_products = self.picking_id.move_ids.mapped("product_id")
                narrowed = narrowed.filtered(
                    lambda l: l.product_id in picking_products
                )
            if len(narrowed) == 1:
                return self._resolve_lot_owner(narrowed, narrowed.product_id)
            self._set_message(
                "more_match",
                _("Multiple lots named %(sn)s found. Click the target "
                  "product row first, then scan again.")
                % {"sn": barcode},
            )
            return True
        if len(lots) == 1:
            return self._resolve_lot_owner(lots, lots.product_id)
        products = self.env["product.product"].search([
            ("barcode", "=", barcode),
            ("company_id", "in", [self.company_id.id, False]),
        ])
        if len(products) > 1:
            self._set_message(
                "more_match",
                _("Multiple products found for barcode: %s") % barcode,
            )
            return True
        if len(products) == 1:
            return self._resolve_lot_owner(self.env["stock.lot"], products)
        return self._create_new_lot_flow(barcode)

    def _create_new_lot_flow(self, barcode):
        """Treat an unknown barcode as a new lot for the current product.

        When the picking's operation type does not allow creating new
        lots/serial numbers (``use_create_lots`` is False), unknown
        barcodes are rejected immediately with a clear error instead of
        silently creating a lot that would only fail at validation time.
        """
        self.ensure_one()
        if not self.product_id and self.active_move_id:
            self.product_id = self.active_move_id.product_id
            self.product_uom_id = self.product_id.uom_id
        if not self.product_id:
            self._set_message(
                "error",
                _("Scan a product barcode or click a product row first."),
            )
            return True
        if not self.picking_id.use_create_lots:
            self._set_message(
                "error",
                _("Serial number/lot %(name)s does not exist. This "
                  "operation type does not allow creating new ones.")
                % {"name": barcode},
            )
            return True
        self.lot_name = barcode
        self.lot_id = False
        self.qty_available = 0.0
        if self.product_id.tracking == "serial":
            self.product_qty = 1.0
            # No location fallback: serial auto-confirm will fail in
            # action_confirm ("No source location scanned") until the
            # operator scans the source location.
            self.action_confirm()
            return True
        self._set_message(
            "info", _("Lot: %s. Enter qty and confirm.") % barcode
        )
        self.step = self._step_index("qty")
        self._set_message_step()
        return True

    def _resolve_lot_owner(self, lot, product):
        """Identify whether ``product`` belongs to this picking.

        - Product in picking.move_ids → switch product_id and bind lot.
        - Unrelated product → error.
        """
        self.ensure_one()
        if not self.picking_id:
            self._set_message("error", _("No transfer selected"))
            return True
        component_moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if component_moves:
            self.product_id = product
            if self.active_move_id and self.active_move_id.product_id != product:
                self.active_move_id = False
            self.product_uom_id = product.uom_id
            if lot:
                self.lot_id = lot
                self.lot_name = lot.name
                self._compute_qty_available()
                if product.tracking == "serial":
                    self.product_qty = 1.0
                    self.action_confirm()
                    self._set_message_step()
                    return True
                self._set_message(
                    "info", _("Lot: %s. Enter qty and confirm.") % lot.name
                )
                self.step = self._step_index("qty")
            else:
                self.lot_id = False
                self.lot_name = False
                if product.tracking != "none":
                    self._set_message(
                        "info", _("Product: %s. Scan lot.") % product.name
                    )
                    self.step = self._step_index("lot")
                else:
                    self._set_message(
                        "info",
                        _("Product: %s. Enter qty and confirm.") % product.name,
                    )
                    self.step = self._step_index("qty")
            self._set_message_step()
            return True
        self._set_message(
            "error",
            _("Lot belongs to product %(name)s which is not part of this transfer")
            % {"name": product.name},
        )
        return True

    def _create_new_lot(self):
        if not self.lot_name or not self.product_id:
            return False
        existing = self.env["stock.lot"].search([
            ("name", "=", self.lot_name),
            ("product_id", "=", self.product_id.id),
        ])
        if existing:
            return existing
        return self.env["stock.lot"].create({
            "name": self.lot_name,
            "product_id": self.product_id.id,
            "company_id": self.company_id.id if self.company_id else self.env.company.id,
        })

    def _compute_qty_available(self):
        if not self.product_id or not self.location_id:
            self.qty_available = 0.0
            return
        domain = [
            ("product_id", "=", self.product_id.id),
            ("location_id", "=", self.location_id.id),
        ]
        if self.lot_id:
            domain.append(("lot_id", "=", self.lot_id.id))
        # Barcode scenario: at most a handful of quants for one product +
        # location (+ optional lot). search+mapped is clearer than the
        # Odoo 19 _read_group tuple format and avoids the deprecated
        # read_group API.
        quants = self.env["stock.quant"].search(domain)
        self.qty_available = sum(quants.mapped("quantity"))

    # --- Action methods ---
    def action_confirm(self):
        """Confirm the scanned product and update stock move lines."""
        if not self._check_selector_resolved():
            return False
        if self.picking_state == "draft":
            self._set_message(
                "error", _("Transfer is draft, confirm it before scanning")
            )
            return False
        if self.picking_state in ("done", "cancel"):
            self._set_message(
                "error",
                _("Transfer is %(state)s, cannot scan")
                % {"state": self.picking_state},
            )
            return False
        if not self.product_id:
            self._set_message("error", _("No product scanned"))
            return False
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        if self.barcode_scan_dest_location and not self.location_dest_id:
            self._set_message(
                "error", _("No destination location scanned")
            )
            return False
        if self.product_id.tracking != "none" and not self.lot_id and not self.lot_name:
            self._set_message("error", _("Lot required for tracked product"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", _("Quantity must be positive"))
            return False

        if not self.lot_id and self.lot_name and self.product_id.tracking != "none":
            self.lot_id = self._create_new_lot()

        move_dic = self._process_stock_move_line()
        if move_dic:
            self._set_message(
                "success",
                _("Product scanned: %(prod)s x%(qty)s")
                % {"prod": self.product_id.name, "qty": self.product_qty},
            )
            self._clean_values()
            return move_dic
        return False

    def _process_stock_move_line(self):
        """Find matching picking move and update/create move line.

        SET semantics (not ADD): matching line quantity is replaced.
        New lines redistribute demand from other lines so a lot
        substitution does not silently double consumption.

        picked write: every created/updated line gets picked=True.
        move.picked is NOT set explicitly — it is computed from
        move_line_ids.picked. Setting move.picked directly triggers
        _inverse_picked, which marks ALL lines of the move as picked
        (wrong for serial products picked one-by-one).
        """
        self.ensure_one()
        if not self.picking_id:
            return False
        moves = self.picking_id.move_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state != "cancel"
        )
        if not moves:
            self._set_message(
                "error",
                _("Product %(name)s is not part of this transfer")
                % {"name": self.product_id.name},
            )
            return False

        existing_lines = moves.mapped("move_line_ids").filtered(
            lambda l: (
                l.product_id == self.product_id
                and (not self.location_id or l.location_id == self.location_id)
                and (not self.lot_id or l.lot_id == self.lot_id)
            )
        )
        other_lines = moves.mapped("move_line_ids") - existing_lines
        other_lines_qty = sum(other_lines.mapped("quantity"))
        total_demand = sum(m.product_uom_qty for m in moves)
        force = self.env.context.get("force_create_move", False)
        rounding = self.product_id.uom_id.rounding

        move_lines_dic = {}

        if existing_lines:
            max_quantity = total_demand - other_lines_qty
            if (
                float_compare(self.product_qty, max_quantity,
                              precision_rounding=rounding) > 0
                and not force
            ):
                self._set_message(
                    "more_match",
                    _("Quantity exceeds demand (max: %s)") % max_quantity,
                )
                self.visible_force_done = True
                return False
            line = existing_lines[:1]
            increase = self.product_qty - line.quantity
            if increase > 0:
                for extra in (existing_lines - line):
                    take = min(extra.quantity, increase)
                    extra.quantity = extra.quantity - take
                    increase -= take
                    if float_is_zero(extra.quantity,
                                     precision_rounding=rounding):
                        extra.unlink()
                    if increase <= 0:
                        break
            line.quantity = self.product_qty
            line.picked = True
            if self.lot_id and not line.lot_id:
                line.lot_id = self.lot_id.id
                line.lot_name = self.lot_id.name
            # NOTE: do NOT set line.move_id.picked here. move.picked is
            # computed from move_line_ids.picked; setting it explicitly
            # triggers _inverse_picked which marks ALL lines of the move
            # as picked — wrong for serial products where each serial is
            # picked individually.
            move_lines_dic[line.move_id.id] = line
        else:
            is_serial = self.product_id.tracking == "serial"
            excess = other_lines_qty + self.product_qty - total_demand
            if excess > 0:
                for line in other_lines.sorted(key=lambda l: l.id):
                    if is_serial and line.picked:
                        continue
                    take = min(line.quantity, excess)
                    line.quantity = line.quantity - take
                    excess -= take
                    if float_is_zero(line.quantity,
                                     precision_rounding=rounding):
                        line.unlink()
                    if excess <= 0:
                        break
            if excess > 0 and not force:
                self._set_message(
                    "more_match",
                    _("Quantity exceeds demand (max: %s)") % total_demand,
                )
                self.visible_force_done = True
                return False
            move = moves[:1]
            sml_vals = {
                "move_id": move.id,
                "product_id": self.product_id.id,
                "product_uom_id": move.product_uom.id or self.product_id.uom_id.id,
                "quantity": self.product_qty,
                "picked": True,
                "location_id": self.location_id.id,
                "location_dest_id": (
                    self.location_dest_id.id
                    if self.location_dest_id
                    else move.location_dest_id.id
                ),
                "lot_id": self.lot_id.id if self.lot_id else False,
                "lot_name": self.lot_id.name if self.lot_id else self.lot_name or False,
            }
            new_line = self.env["stock.move.line"].create(sml_vals)
            # move.picked auto-computes from new_line.picked (see note above).
            move_lines_dic[move.id] = new_line

        return move_lines_dic

    def action_force_done(self):
        return self.with_context(force_create_move=True).action_confirm()

    def action_consume_by_demand(self):
        """One-click consume the full demand of the active/non-tracked
        product.

        Tracked products (serial + lot) are rejected — lot/serial picking
        requires scanning each lot. Only non-tracked products can be
        consumed by demand. The demand is move.product_uom_qty (the full
        requested quantity, independent of reservation).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        product = self.product_id or (
            self.active_move_id.product_id if self.active_move_id else False
        )
        if not product:
            self._set_message("error", _("No product selected"))
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                _("Cannot consume tracked product by demand; scan the lot"),
            )
            return False
        # Full demand from the move (not reservation)
        move = self.active_move_id or self.picking_id.move_ids.filtered(
            lambda m: m.product_id == product and m.state not in ("done", "cancel")
        )[:1]
        if not move:
            self._set_message(
                "error",
                _("Product %s is not part of this transfer") % product.name,
            )
            return False
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.active_move_id = move
        self.product_qty = move.product_uom_qty
        # action_confirm internally calls _clean_values → _set_message_step,
        # which would overwrite any custom message. So set the success
        # message AFTER action_confirm returns.
        result = self.action_confirm()
        if result:
            self._set_message(
                "success",
                _("Consumed full demand: %(prod)s x%(qty)s")
                % {"prod": product.name, "qty": move.product_uom_qty},
            )
        return result

    def action_consume_with_qty(self, qty):
        """Consume a specific quantity (pencil button on a move row).

        Sets the active move + qty then delegates to action_confirm.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.active_move_id:
            self._set_message("error", _("No product row selected"))
            return False
        product = self.active_move_id.product_id
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        qty = float(qty) if qty else 0.0
        if qty <= 0:
            self._set_message("error", _("Quantity must be positive"))
            return False
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.product_qty = qty
        result = self.action_confirm()
        if result:
            self._set_message(
                "success",
                _("Consumed: %(prod)s x%(qty)s")
                % {"prod": product.name, "qty": qty},
            )
        return result

    def action_validate_picking(self):
        """Validate the current picking (finalize the transfer).

        Wraps picking.button_validate(). When Odoo returns a backorder
        wizard (act_window dict), the views key is patched so the OWL
        client action can open it without crashing on _preprocessAction.
        Returns True when the picking is validated directly (no wizard).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        picking = self.picking_id
        if not picking:
            self._set_message("error", _("No transfer selected"))
            return False
        # Pack check: if required, all picked lines must be in a package
        if self._lines_need_pack(picking):
            unpacked = picking.move_line_ids.filtered(
                lambda l: l.picked and not l.result_package_id
            )
            if unpacked:
                self._set_message(
                    "error",
                    _("All picked products must be put into a package "
                      "before validation.")
                )
                return False
        result = picking.button_validate()
        if isinstance(result, dict):
            # Crash-guard only: core _action_generate_backorder_wizard
            # already returns 'views': [(view.id, 'form')]. This setdefault
            # is NOT a restore of the backorder's specific view — it only
            # ensures the 'views' key exists so the client action's
            # _preprocessAction (which maps views) cannot crash on a
            # dict that somehow lacks it. view_id=False falls back to the
            # model's default form view.
            result.setdefault("views", [(False, "form")])
            return result
        # result is True (picking validated) or None/False (already done)
        return result

    def action_put_in_pack(self):
        """Put all picked (and unpacked) move lines into a new package.

        Calls picking.action_put_in_pack() with the barcode_view context.

        Return value contract (forwarded to the frontend's three-state
        handler ``_handleActionResult``):
          - False: guard blocked it / no transfer / exception
          - True:  packed directly (operation type does not require a
                   package type)
          - dict:  Odoo's ``stock.put.in.pack`` wizard action — the
                   operation type requires a package type
                   (``set_package_type``). The frontend opens it; once
                   the operator picks a package type and confirms, Odoo
                   creates the package and the frontend refreshes.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        picking = self.picking_id
        if not picking:
            self._set_message("error", _("No transfer selected"))
            return False
        if not picking.move_line_ids.filtered(
            lambda l: l.picked and not l.result_package_id
        ):
            self._set_message(
                "info",
                _("No unpacked picked products to pack."),
            )
            return True
        try:
            result = picking.with_context(barcode_view=True).action_put_in_pack()
        except Exception as exc:
            self._set_message(
                "error",
                _("Failed to put in package: %(msg)s") % {"msg": str(exc)},
            )
            return False
        # If Odoo returned a wizard action (package type required),
        # forward it to the frontend so the operator can choose.
        if isinstance(result, dict) and result.get("type"):
            return result
        self._set_message(
            "success",
            _("Products have been put into a package."),
        )
        return True

    def set_active_move(self, move_id):
        """Bind the operator's target move (RPC entry for row click).

        Rejects moves that do not belong to the current picking so a
        stale click cannot redirect the scan to an unrelated move.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.picking_id:
            return False
        move = self.env["stock.move"].browse(move_id)
        if not move or move.picking_id != self.picking_id:
            return False
        self.active_move_id = move
        self._set_message_step()
        return True

    def action_force_add(self, product_id=None):
        """Temporarily add a non-tracked product to the picking and
        consume the scanned quantity.

        Creates a new stock.move on the current picking (explicit fields:
        picking_id, product_id, product_uom_qty, location_id,
        location_dest_id from picking.location_dest_id), confirms it, then
        consumes via ``_process_stock_move_line``.

        Tracked products are rejected (lot/serial picking requires lot
        scanning).
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not self.picking_id:
            self._set_message("error", _("No transfer selected"))
            return False
        if product_id:
            product = self.env["product.product"].browse(product_id)
        else:
            product = self.product_id
        if not product:
            self._set_message("error", _("No product to add"))
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                _("Force add only supports non-tracked products"),
            )
            return False
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", _("Quantity must be positive"))
            return False
        # Create the new move on the picking. location_dest_id is taken
        # from the picking (the new move has no inheritance chain).
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": self.product_qty,
            "product_uom": self.product_uom_id.id or product.uom_id.id,
            "picking_id": self.picking_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": (
                self.location_dest_id.id
                if self.location_dest_id
                else self.picking_id.location_dest_id.id
            ),
        })
        # merge=False keeps the new move distinct from existing moves for
        # the same product (otherwise _action_confirm merges them and the
        # newly-created record is unlinked, breaking active_move_id).
        move._action_confirm(merge=False)
        # Refresh the picking's move_ids cache so _process_stock_move_line
        # (which searches self.picking_id.move_ids) sees the new move.
        self.picking_id.invalidate_recordset(["move_ids"])
        # Set product context so _process_stock_move_line finds the move
        self.product_id = product
        self.product_uom_id = self.product_uom_id or product.uom_id
        self.active_move_id = move
        move_dic = self._process_stock_move_line()
        if move_dic:
            self.visible_force_add = False
            # _clean_values calls _set_message_step which overwrites
            # custom messages, so set success AFTER it.
            self._clean_values()
            self._set_message(
                "success",
                _("Added & picked: %(prod)s x%(qty)s")
                % {"prod": product.name, "qty": self.product_qty},
            )
            return move_dic
        return False

    def action_force_add_from_barcode(self, barcode):
        """Force-add a product from an unmatched barcode.

        Frontend contract: when ``process_barcode_and_dispatch`` returns
        ``message_type == "not_found"``, the frontend offers a "Force add"
        button. The user clicks it and the frontend calls this method
        with the same barcode string. The server resolves the product by
        barcode (single source of truth — the frontend never RPCs
        product search) and delegates to ``action_force_add``.
        """
        self.ensure_one()
        if not self._check_selector_resolved():
            return False
        if not barcode:
            self._set_message("error", _("No barcode to add"))
            return False
        product = self.env["product.product"].search(
            [("barcode", "=", barcode)], limit=1
        )
        if not product:
            self._set_message(
                "error",
                _("No product found for barcode: %s") % barcode,
            )
            return False
        if product.tracking != "none":
            self._set_message(
                "error",
                _("Force add only supports non-tracked products"),
            )
            return False
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", _("Quantity must be positive"))
            return False
        return self.action_force_add(product_id=product.id)

    # --- Remove a scanned lot / SN ---
    def action_remove_move_lot(self, move_id, lot_id):
        """Remove a scanned lot/SN from a picking move.

        Lets the operator correct a mis-scanned serial or lot without
        leaving the scan flow. Behaviour mirrors the move-line lifecycle:
          - serial (1 line = 1 SN = qty 1): unlink the move line.
          - lot (qty > 1 on a single line): decrement quantity by 1; if
            it reaches 0, unlink the line.

        Does NOT delete the ``stock.lot`` record itself — it is an
        inventory entity; only the picking move line is undone.

        After removal the move's ``picked`` flag recomputes from its
        remaining move lines automatically.

        :param move_id: stock.move id (must belong to this picking)
        :param lot_id: stock.lot id to remove from that move
        :return: True on success, False if move_id/lot_id invalid
        """
        self.ensure_one()
        if not self.picking_id:
            return False
        move = self.picking_id.move_ids.filtered(lambda m: m.id == move_id)
        if not move:
            return False
        lines = move.move_line_ids.filtered(lambda l: l.lot_id.id == lot_id)
        if not lines:
            return False
        line = lines[0]
        if line.quantity > 1:
            line.quantity -= 1
            if line.quantity <= 0:
                line.unlink()
        else:
            line.unlink()
        return True

    # --- Cleanup ---
    def _clean_values(self):
        """Clean scanned values after successful confirmation.

        product_id is cleared, which cascades to product_tracking
        (related field) and re-enables the lot step in the UI.
        """
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.visible_force_done = False
        self.visible_force_add = False
        self.step = self._step_index("product")
        self._set_message_step()
