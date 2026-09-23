# Copyright 2026 OpenViking
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo import _, api, fields, models

from odoo.tools.float_utils import float_compare, float_is_zero


class WizStockBarcodesMrp(models.TransientModel):
    _name = "wiz.stock.barcodes.mrp"
    _inherit = "barcodes.barcode_events_mixin"
    _description = "Wizard to read barcode on manufacturing orders"
    _transient_max_hours = 48

    # --- Production context ---
    # NB: NOT field-level readonly. Readonly fields are dropped from the
    # client save payload, so a hardware/manual scan landing on a *new*
    # onchange RPC would browse a record with production_id=False and
    # every cross-request scan step would fall through ("Barcode not
    # found"). The form renders it read-only via invisible/plain fields.
    production_id = fields.Many2one(
        comodel_name="mrp.production",
        string="Manufacturing Order",
    )
    production_state = fields.Selection(related="production_id.state")
    # D3: stash flag set when action_finish_production returns a dialog
    # action (consumption warning / backorder). _onchange_production_state
    # consumes it after the dialog closes and the client reloads the
    # record, flipping the placeholder info banner to a real "Production
    # done" success banner.
    pending_finish = fields.Boolean(
        string="Pending finish",
        help="Set by action_finish_production's dialog path; consumed by "
             "_onchange_production_state once the MO actually goes done.",
        default=False,
    )
    workorder_id = fields.Many2one(
        comodel_name="mrp.workorder",
        string="Work Order",
    )
    workorder_state = fields.Selection(related="workorder_id.state")
    production_product_id = fields.Many2one(
        comodel_name="product.product",
        related="production_id.product_id",
        string="Product to Produce",
    )
    production_product_qty = fields.Float(
        related="production_id.product_qty",
        string="Qty to Produce",
    )
    production_qty_producing = fields.Float(
        related="production_id.qty_producing",
        string="Qty Producing",
    )
    production_location_src_id = fields.Many2one(
        comodel_name="stock.location",
        related="production_id.location_src_id",
        string="Components Location",
    )
    production_location_dest_id = fields.Many2one(
        comodel_name="stock.location",
        related="production_id.location_dest_id",
        string="Finished Products Location",
    )
    company_id = fields.Many2one(related="production_id.company_id")

    # --- Finished product lot scanning ---
    finished_product_tracking = fields.Selection(
        related="production_id.product_id.tracking", readonly=True,
    )
    finished_lot_id = fields.Many2one(
        comodel_name="stock.lot",
        string="Finished Lot/Serial",
        # NB: no field-level dynamic domain here. A model-level domain
        # string referencing another field is evaluated client-side through
        # the fallback path and produced an invalid stock.lot search_read
        # domain ("Domain() invalid item in domain: <product id>") when the
        # lot autocomplete/Search-More dialog used it. The product filter
        # lives on the view node instead; action_apply_finished_lot() guards
        # the chosen lot server-side.
    )
    finished_lot_name = fields.Char(string="Finished Lot Name")
    finished_qty_producing = fields.Float(
        string="Finished Qty", digits="Product Unit of Measure",
    )

    # --- Scanned values ---
    barcode = fields.Char()
    res_model_id = fields.Many2one(comodel_name="ir.model", index=True)
    res_id = fields.Integer(index=True)
    location_id = fields.Many2one(
        comodel_name="stock.location",
        string="Source Location",
    )
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Component",
        domain="[('type', '=', 'consu')]",
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
    message_step = fields.Char(readonly=True)
    step = fields.Integer(default=1)
    visible_force_done = fields.Boolean()
    visible_force_add = fields.Boolean(
        string="Force Add",
        help="Show the 'Force Add' button to consume a product not in the BOM",
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

    # --- TODO-C4: component checklist ---
    component_move_ids = fields.One2many(
        related="production_id.move_raw_ids",
        string="Component Checklist",
        readonly=True,
    )

    # --- TODO-B1: work-order queue ---
    queue_mode = fields.Selection(
        [("my", "My Work Orders"), ("all", "All MO")],
        string="Queue View",
        default="my",
    )
    queue_filter_today = fields.Boolean(string="Due Today")
    queue_filter_priority = fields.Boolean(string="High Priority")
    queue_workorders_ids = fields.Many2many(
        comodel_name="mrp.production",
        string="Queue",
        compute="_compute_queue_workorders",
    )

    # --- TODO-B2: scan-first MO switching ---
    pending_switch_production_ids = fields.Many2many(
        comodel_name="mrp.production",
        string="Candidate MOs",
        help="MOs matching an ambiguous scan; the operator picks one to "
        "switch to.",
    )
    visible_switch_selector = fields.Boolean(
        string="Show MO Selector",
        help="Display the ambiguous-MO selection list.",
    )
    # B2 stores per-MO scan snapshots when switching; B3 restores them.
    scan_progress_stash = fields.Json(
        string="Stashed Scan Progress",
    )

    # --- OE-aligned UI conventions (ent stock_barcode_mrp) ---
    queue_visible = fields.Boolean(
        string="Queue Visible",
        default=False,
        help="Show the work-order queue drawer below the scan zone. The "
        "enterprise app keeps the queue off the scan screen; it only "
        "appears when no MO is active or the operator opens it from Tools.",
    )
    show_tools = fields.Boolean(
        string="Show Tools",
        default=False,
        help="Expand the Tools panel with secondary operations (manual "
        "entry, force actions, MO details, queue). No <details> precedent "
        "exists in core views, so visibility is toggled via this boolean.",
    )
    components_availability = fields.Char(
        related="production_id.components_availability",
        string="Component Status",
    )
    components_availability_state = fields.Selection(
        related="production_id.components_availability_state",
        string="Component Availability",
    )
    # OE scan-screen header shows scheduled date / source document / state.
    # NB: mrp.production date field is `date_start` in Odoo 19 (was
    # `date_planned_start` in 17.0).
    production_date_planned = fields.Datetime(
        related="production_id.date_start",
        string="Scheduled Date",
    )
    production_origin = fields.Char(
        related="production_id.origin",
        string="Source Document",
    )

    @api.depends("production_id.move_raw_ids", "product_id")
    def _compute_totals(self):
        for rec in self:
            rec.total_demand = 0.0
            rec.total_done = 0.0
            if not rec.production_id or not rec.product_id:
                continue
            moves = rec.production_id.move_raw_ids.filtered(
                lambda m: m.product_id == rec.product_id and m.state != "cancel"
            )
            for move in moves:
                rec.total_demand += move.product_uom_qty
                rec.total_done += move.quantity

    @api.depends("queue_mode", "queue_filter_today", "queue_filter_priority")
    def _compute_queue_workorders(self):
        """Return the list of MOs shown in the queue area.

        Default (My Work Orders): MOs that have a workorder on a workcenter
        assigned to the current user, in confirmed/progress state. All MO
        mode drops the workcenter filter. Optional filters: due today,
        high priority.

        Note: mrp.production.workcenter_id is a non-stored, non-computed
        placeholder field, so we filter via mrp.workorder.workcenter_id
        and resolve back to productions.
        """
        for wiz in self:
            domain = [("state", "in", ("confirmed", "progress"))]
            if wiz.queue_mode == "my":
                wc_ids = self.env.user.mrp_workcenter_ids.ids
                workorders = self.env["mrp.workorder"].search([
                    ("workcenter_id", "in", wc_ids),
                    ("state", "not in", ("done", "cancel")),
                ])
                domain.append(("id", "in", workorders.mapped("production_id").ids))
            if wiz.queue_filter_today:
                today = fields.Date.context_today(self)
                domain += [
                    ("date_deadline", ">=", today),
                    ("date_deadline", "<=", today),
                ]
            if wiz.queue_filter_priority:
                domain.append(("priority", ">=", "1"))
            wiz.queue_workorders_ids = self.env["mrp.production"].search(domain)

    def action_switch_queue_mode(self):
        """Toggle between My Work Orders and All MO."""
        self.ensure_one()
        self.queue_mode = "all" if self.queue_mode == "my" else "my"
        return True

    def action_toggle_queue_visible(self):
        """Show/hide the queue drawer; the scan zone stays first, as the
        enterprise app keeps the queue off the scan screen. Opening the
        queue from Tools also collapses the Tools panel so only one
        auxiliary drawer is visible at a time."""
        self.ensure_one()
        self.queue_visible = not self.queue_visible
        if self.queue_visible:
            self.show_tools = False
        return True

    def action_toggle_show_tools(self):
        """Expand/collapse the Tools panel with secondary operations."""
        self.ensure_one()
        self.show_tools = not self.show_tools
        if self.show_tools:
            self.queue_visible = False
        return True

    def action_toggle_queue_filter(self, filter_name):
        """Toggle a queue quick filter (today / priority)."""
        self.ensure_one()
        if filter_name == "today":
            self.queue_filter_today = not self.queue_filter_today
        elif filter_name == "priority":
            self.queue_filter_priority = not self.queue_filter_priority
        return True

    def action_open_queue_mo(self):
        """Switch the active production to the MO clicked in the queue."""
        self.ensure_one()
        if not self.queue_workorders_ids:
            return True
        # The clicked MO is the last one in the selection (Odoo passes the
        # clicked record through the queue_workorders_ids write).
        target = self.queue_workorders_ids[-1]
        if target and target != self.production_id:
            # Same path as scan-first switching: stashes current progress
            # and restores any progress previously left on the target MO.
            self._switch_production(target)
        return True

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "{} - {} - {}".format(
                _("Barcode reader"),
                rec.production_id.name or _("MRP"),
                self.env.user.name,
            )

    # --- Lifecycle ---
    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wiz in wizards:
            wiz._set_default_values()
        return wizards

    @api.onchange("production_id")
    def onchange_production_id(self):
        self._set_default_values()

    @api.onchange("production_state")
    def _onchange_production_state(self):
        """D3: after a dialog-close reload, if the MO actually went done,
        swap the placeholder 'Resolving consumption warning...' banner for
        a real 'Production done' success banner. Consumes the
        pending_finish flag so a later unrelated state change does not
        re-trigger the success banner.
        """
        if self.pending_finish and self.production_state == "done":
            self._set_message(
                "success", _("Production done: %s") % self.production_id.name
            )
            self.pending_finish = False

    def _set_default_values(self):
        """Set default source location and qty from the MO."""
        # OE-aligned queue behaviour: no active MO -> the queue is the
        # entry screen; once a MO is active the queue collapses so the
        # scan zone owns the screen.
        self.queue_visible = not self.production_id
        if self.production_id:
            if not self.location_id:
                self.location_id = self.production_id.location_src_id
            if not self.finished_qty_producing:
                self.finished_qty_producing = self.production_id.product_qty
            # If finished product is tracked and no lot yet, start at step 0
            if (
                self.production_id.product_id.tracking != "none"
                and not self.finished_lot_id
            ):
                self.step = 0
            else:
                self.step = 1
            self._set_message_step()

    # --- Barcode scanning entry point ---
    def on_barcode_scanned(self, barcode):
        """Hardware path: core barcode_handler widget writes
        `_barcode_scanned` → core mixin onchange calls this. Processes
        directly and deliberately does NOT write `barcode`, so the
        client-side onchange chain can never double-fire the manual
        entry handler below.

        NB: must NOT return _process_barcode's bool. The core
        barcodes.barcode_events_mixin._on_barcode_scanned transparently
        returns our value to the ORM onchange framework, and
        orm/models.py._apply_onchange_methods does `if res.get('value'):`
        (~L6996-6998) — a True return therefore reaches `True.get` and
        crashes the web client with `AttributeError: 'bool' object has
        no attribute 'get'`. B2's unit tests missed this because the
        action_barcode_scanned helper calls _on_barcode_scanned()
        directly without inspecting the return value; see
        test_b2_on_barcode_scanned_returns_none_not_bool and
        test_b2_onchange_browser_path_does_not_crash.
        """
        self._process_barcode(barcode.strip() if barcode else "")

    @api.onchange("barcode")
    def _onchange_barcode_scan(self):
        """Manual scan box path: the visible `barcode` char field is
        the scan entry for tablets/browsers without a hardware scanner
        (the barcode_handler widget renders nothing). Clears the value
        so the same code can be scanned twice in a row."""
        if self.barcode:
            barcode = self.barcode
            self.barcode = False
            self._barcode_scanned = False
            self._process_barcode(barcode)
        # NB: onchange methods must return None or a dict — returning
        # True crashes the web client ('bool' object has no 'get').

    def _process_barcode(self, barcode):
        """Main barcode dispatch: try finished lot → location → product → lot.

        C5: scan-first entry — when no MO is selected (production_id is
        False), _scan_finished_lot_reverse runs BEFORE _scan_finished_lot
        because the latter requires production_id to be set. The reverse
        lookup matches the scanned barcode against MOs that have the SN
        pre-assigned in lot_producing_ids.
        """
        if not barcode:
            return
        # C5: scan-first SN reverse lookup (only fires when no MO is set)
        if self._scan_finished_lot_reverse(barcode):
            return True
        # Try finished product lot first (if tracked and not yet scanned)
        if self._scan_finished_lot(barcode):
            return True
        # Try manufacturing order reference (scan-first MO switching)
        if self._scan_production(barcode):
            return True
        # Try location
        if self._scan_location(barcode):
            return True
        # Try product
        res = self._scan_product(barcode)
        if res:
            return res
        # Try lot
        if self._scan_lot(barcode):
            return True
        # Last resort: unknown barcode → record as a pending finished lot
        # name (actual lot creation happens at Apply Lot / Finish). Every
        # scanner above has already declined the barcode, so this cannot
        # swallow MO refs / location barcodes / product barcodes / lots.
        if self._accept_new_finished_lot(barcode):
            return True
        # Not found
        self._set_message("not_found", _("Barcode not found: %s") % barcode)
        return True

    def process_barcode_and_dispatch(self, barcode):
        """One-shot RPC entry for the OWL MrpScanApp client action.

        Runs the existing _process_barcode(barcode) logic, then:
        - if visible_switch_selector is set (multi-match), also calls
          action_open_candidate_list() to fetch the act_window dict so
          the client can action.doAction(result.action) into the
          filtered mrp.production list in one round-trip (no extra
          button click — the onchange-can't-return-action trade-off
          is eliminated by the client-action route).
        - returns {action, state} where action is None or an
          act_window dict, and state is a JSON-serializable snapshot
          of the wizard fields needed by the client UI.

        Unlike _onchange_barcode_scan / on_barcode_scanned, this is a
        direct method call (no onchange framework), so it CAN embed an
        act_window action in the response.
        """
        self.ensure_one()
        self._process_barcode(barcode)
        action = None
        if self.visible_switch_selector and self.pending_switch_production_ids:
            action = self.action_open_candidate_list()
        return {
            "action": action,
            "state": self.get_scan_state(),
        }

    def get_scan_state(self):
        """JSON-serializable snapshot of the wizard state for the OWL
        client action to render.

        Includes: wiz_id, step, message/message_type/message_step,
        MO + product + location + lot display names,
        finished_qty_producing, visible_switch_selector, and
        component_move_ids as a list of dicts (id, product_name,
        demand, reserved quantity, picked, state).
        """
        self.ensure_one()
        production = self.production_id
        components = []
        for mv in self.component_move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        ):
            move_lines = mv.move_line_ids
            picked_all = bool(move_lines) and all(l.picked for l in move_lines)
            components.append({
                "id": mv.id,
                "product_name": mv.product_id.display_name or "",
                "demand": mv.product_uom_qty,
                "quantity": sum(move_lines.mapped("quantity")),
                "picked": picked_all,
                "state": mv.state,
            })
        return {
            "wiz_id": self.id,
            "step": self.step,
            "message": self.message or "",
            "message_type": self.message_type or "info",
            "message_step": self.message_step or "",
            "production_id": production.id,
            "production_name": production.name or "",
            "production_product_name": self.production_product_id.display_name or "",
            "location_name": self.location_id.display_name or "",
            "product_name": self.product_id.display_name or "",
            "lot_name": self.lot_id.display_name or "",
            "finished_qty_producing": self.finished_qty_producing or 0.0,
            "visible_switch_selector": bool(self.visible_switch_selector),
            # Button visibility fields (mirror the old form invisible attrs)
            "production_state": self.production_state or "",
            "finished_product_tracking": self.finished_product_tracking or "none",
            "product_id": self.product_id.id or False,
            "product_tracking": self.product_tracking or "none",
            "product_qty": self.product_qty or 0.0,
            "lot_id": self.lot_id.id or False,
            "lot_name_raw": self.lot_name or "",
            "finished_lot_id": self.finished_lot_id.id or False,
            "finished_lot_name": self.finished_lot_name or "",
            "visible_force_done": bool(self.visible_force_done),
            "components": components,
        }

    def _scan_finished_lot_reverse(self, barcode):
        """Scan-first entry: scan a finished product's SN to land on its MO.

        Only active when no MO is selected (production_id is False); when
        a MO is already set, the regular _scan_finished_lot handles SN
        binding. Reverse lookup by lot_producing_ids — the M2m field where
        the SN was pre-assigned to the MO (user-confirmed semantics).

        Path:
          1. Search stock.lot by name (company-scoped); 0 -> return False
             so the SN can be tried as a component lot downstream.
          2. Reverse search mrp.production where lot_producing_ids contains
             the lot. 0 -> return False (SN is a component lot, not an
             unbound SN error — fall through to the next scanner).
          3. SN whose only MO is done -> 'MO already done' info, no switch.
          4. 1 active MO -> _switch_production + bind finished_lot_id +
             _auto_fill_components (consistent with scanning the finished
             product barcode).
          5. Multi active MOs -> set visible_switch_selector flag and
             pending_switch_production_ids. ORM onchange cannot return an
             action directly, so the operator clicks the 'View candidate
             MOs' button (type=object) to open the filtered list.
        """
        self.ensure_one()
        if self.production_id:
            return False  # Regular _scan_finished_lot handles this case
        lots = self.env["stock.lot"].search([
            ("name", "=", barcode),
            ("company_id", "in", [self.env.company.id, False]),
        ])
        if not lots:
            return False  # Not a known lot -> fall through
        if len(lots) > 1:
            self._set_message(
                "more_match",
                _("Multiple lots found for %s — refine barcode.") % barcode,
            )
            return True
        lot = lots
        # Reverse lookup by lot_producing_ids — the field where the SN
        # was pre-assigned to the MO (user-confirmed semantics).
        assigned_mos = self.env["mrp.production"].search([
            ("lot_producing_ids", "in", lot.id),
        ])
        if not assigned_mos:
            # SN exists but is not assigned to any MO — probably a
            # component lot; fall through so downstream scanners handle
            # it (do NOT raise an 'unbound SN' error).
            return False
        done_mos = assigned_mos.filtered(lambda m: m.state == "done")
        active_mos = assigned_mos.filtered(
            lambda m: m.state in ("confirmed", "progress", "to_close")
        )
        if not active_mos:
            self._set_message(
                "info",
                _("MO %s is already done") % done_mos[0].name,
            )
            return True
        if len(active_mos) == 1:
            self._switch_production(active_mos)
            # Validate product match before binding lot
            if self.production_id.product_id == lot.product_id:
                self.finished_lot_id = lot
                self.finished_lot_name = lot.name
                # Consistent with scanning the finished product barcode:
                # auto-fill components once the lot is bound.
                self._auto_fill_components()
            return True
        # Multiple active MOs -> flag; operator clicks 'View candidate MOs'
        self.pending_switch_production_ids = active_mos
        self.visible_switch_selector = True
        self._set_message(
            "more_match",
            _("Found %s MOs for SN %s — click 'View candidate MOs' to pick.")
            % (len(active_mos), barcode),
        )
        return True

    def _scan_finished_lot(self, barcode):
        """Scan an EXISTING lot/serial of the finished product.

        Unknown barcodes fall through the dispatch chain; the last-resort
        handler _accept_new_finished_lot records the barcode as a pending
        finished lot name (lot created at apply/finish time). So location /
        MO / product barcodes can never be swallowed here.

        Works at any step (not just step 0) so the operator can bind the
        finished lot after components are auto-filled.
        """
        if not self.production_id:
            return False
        finished_product = self.production_id.product_id
        if finished_product.tracking == "none":
            return False
        if self.finished_lot_id:
            return False
        lot_domain = [("name", "=", barcode), ("product_id", "=", finished_product.id)]
        lots = self.env["stock.lot"].search(lot_domain)
        if not lots:
            return False
        if len(lots) > 1:
            self._set_message("more_match", _("Multiple finished lots found"))
            return True
        self.finished_lot_id = lots
        self.finished_lot_name = lots.name
        self._auto_fill_components()
        return True

    def _accept_new_finished_lot(self, barcode):
        """Last-resort fallback: record an unknown barcode as a pending
        finished lot name for the current MO.

        Does NOT create the stock.lot record or write
        production.lot_producing_ids — those happen at Apply Lot /
        Finish Production (consistent with _scan_finished_lot, and keeps
        the scan phase free of DB side effects so a mistyped SN can be
        cleared without polluting the MO).

        Only fires when ALL other scanners failed. Placed at the END of
        the dispatch chain so it cannot swallow MO refs, location barcodes,
        product barcodes, or existing lots of other products.
        """
        if not self.production_id:
            return False
        finished_product = self.production_id.product_id
        if finished_product.tracking == "none":
            return False
        if self.finished_lot_id:
            return False
        # Guard: existing lot of any product → don't shadow it
        if self.env["stock.lot"].search([("name", "=", barcode)], limit=1):
            return False
        self.finished_lot_name = barcode
        self._auto_fill_components()
        self._set_message("info", _("Pending finished lot: %s") % barcode)
        return True

    def _scan_production(self, barcode):
        """Scan-first MO switching by MO reference (mrp.production.name).

        PRECONDITION: shop-floor MO barcodes are assumed to print the MO
        reference (``name``, e.g. WH/MO/00001). Matches are exact. If the
        printed barcode is not the reference, a dedicated barcode field on
        mrp.production must be added later.

        - Active MO matching      -> switch directly (no confirmation).
        - Multiple active MOs     -> show the ambiguous selector.
        - Inactive MO name (draft/done/cancel) -> error, do NOT fall through.
        - No MO named like this   -> return False so the location/product/lot
          scanners keep running (otherwise every normal scan is swallowed).
        """
        self.ensure_one()
        active_states = ("confirmed", "progress", "to_close")
        mos = self.env["mrp.production"].search([
            ("name", "=", barcode),
            ("state", "in", active_states),
        ])
        if not mos:
            # The same reference exists but the MO is not active -> block,
            # since this is clearly an MO barcode that cannot be handled.
            if self.env["mrp.production"].search_count(
                [("name", "=", barcode)], limit=1
            ):
                self._set_message(
                    "error",
                    _("MO %s is not active (draft/done/cancelled)") % barcode,
                )
                return True
            return False
        if len(mos) > 1:
            self.pending_switch_production_ids = mos
            self.visible_switch_selector = True
            self._set_message(
                "more_match",
                _("Multiple MOs found for barcode: %s. Select one.") % barcode,
            )
            return True
        mo = mos
        if self.production_id == mo:
            self._set_message("info", _("Already on MO %s") % mo.name)
            return True
        # _switch_production sets the banner: notice + next instruction.
        self._switch_production(mo)
        return True

    def _scan_location(self, barcode):
        location = self.env["stock.location"].search(
            [("barcode", "=", barcode), ("usage", "=", "internal")], limit=1
        )
        if not location:
            return False
        self.location_id = location
        self._set_message("info", _("Location: %s. Scan component.") % location.name)
        self.step = 2
        self._set_message_step()
        return True

    def _scan_product(self, barcode):
        domain = [("barcode", "=", barcode), ("type", "=", "consu")]
        products = self.env["product.product"].search(domain)
        if not products:
            return False
        if len(products) > 1:
            self._set_message("more_match", _("Multiple products found"))
            return True
        product = products
        # C5: scan-first reverse lookup — only when no MO is selected.
        # Tries to land on the unique active MO producing this product
        # (single match -> switch + auto-fill); multi-match sets the
        # visible_switch_selector flag because ORM onchange cannot
        # return an action directly. The operator clicks the 'View
        # candidate MOs' button (type=object) to open the filtered list.
        # Existing tests stay valid because the branch is gated on
        # `not self.production_id`; when a MO is already set, the
        # original _auto_fill_components / _scan_product_fallback
        # branches below run unchanged.
        if not self.production_id:
            active_mos = self.env["mrp.production"].search([
                ("product_id", "=", product.id),
                ("state", "in", ("confirmed", "progress", "to_close")),
            ])
            if len(active_mos) == 1:
                self._switch_production(active_mos)
                if self.production_id.product_id == product:
                    return self._auto_fill_components()
                return True
            if len(active_mos) > 1:
                self.pending_switch_production_ids = active_mos
                self.visible_switch_selector = True
                self._set_message(
                    "more_match",
                    _("Found %s MOs for %s — click 'View candidate MOs' "
                      "to pick.") % (len(active_mos), product.name),
                )
                return True
            # 0 active MO for this product -> clear error so the
            # operator knows the MO is missing/inactive.
            self._set_message(
                "error",
                _("No active MO for product %s") % product.name,
            )
            return True
        # TODO-A3: scanned the finished product of this MO -> auto-fill
        # all components so the operator only needs to confirm qty.
        if self.production_id and product == self.production_id.product_id:
            return self._auto_fill_components()
        # If the product is NOT a component of the current MO, run the
        # TODO-A1 fallback BEFORE overwriting the in-progress scan state:
        # a MO switch must stash the *old* progress, not the product that
        # triggered the switch.
        if self.production_id:
            component_moves = self.production_id.move_raw_ids.filtered(
                lambda m: m.product_id == product and m.state != "cancel"
            )
            if not component_moves:
                return self._scan_product_fallback(product)
        # Normal component of this MO -> set scanned product on wizard
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 1.0
        self._compute_qty_available()
        if product.tracking != "none":
            self._set_message("info", _("Product: %s. Scan lot.") % product.name)
            self.step = 3
        else:
            self._set_message("info", _("Product: %s. Enter qty and confirm.") % product.name)
            self.step = 4
        self._set_message_step()
        return True

    def action_open_candidate_list(self):
        """Button-triggered path around the onchange-can't-return-action
        limit.

        Scanning a product or SN that matches multiple active MOs sets
        visible_switch_selector in the onchange (called via
        _onchange_barcode_scan / on_barcode_scanned). The operator then
        clicks this button (a type=object button, NOT an onchange) to
        open the filtered mrp.production list. The list replaces this
        wizard (target='current'); the wizard remains in the breadcrumb
        stack, so cancelling the list returns here.

        Trade-off: operator must click an extra button. This is the ORM
        onchange framework's hard constraint — onchange methods can only
        return value/warning/domain dicts, not act_window actions. The
        alternative (frontend JS component) is out of scope per the
        'core barcodes/mrp/stock only' constraint.
        """
        self.ensure_one()
        if not self.pending_switch_production_ids:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.production",
            "view_mode": "list",
            # ``views`` is required by the web client's
            # _preprocessAction when the dict is consumed directly via
            # action.doAction (the B1 client-action RPC path bypasses
            # the /web/dataset/call_button endpoint, whose
            # clean_action() would otherwise generate this key).
            "views": [(False, "list"), (False, "form")],
            "name": _("Candidate MOs (%s)") % len(self.pending_switch_production_ids),
            "domain": [("id", "in", self.pending_switch_production_ids.ids)],
            "context": {"barcode_wizard_id": self.id},
            "target": "current",
        }

    # --- TODO-A3: auto-fill components from finished product scan ---
    def _auto_fill_components(self):
        """Scan-first behavior: scanning the finished product (or its lot)
        auto-fills every component move line by its BOM-scaled demand and
        marks the moves picked. The operator only needs to confirm quantity.

        The MO's raw moves already have reserved move lines (created by core
        action_assign). We scale those existing lines proportionally to the
        demand, never exceeding the reserved quantity:
          - demand <= reserved -> every line is scaled down so the total
            equals demand (full fill).
          - demand >  reserved -> lines are left untouched (scale = 1), so
            only the reserved (available) quantity is filled (partial).
        This respects FIFO/FEFO since we never reorder or re-reserve.
        """
        self.ensure_one()
        production = self.production_id
        if not production:
            self._set_message("error", _("No manufacturing order selected"))
            return True
        qty = self.finished_qty_producing or production.product_qty
        filled = 0
        partial = 0
        for move in production.move_raw_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        ):
            demand = move.product_uom.round(move.unit_factor * qty)
            move_lines = move.move_line_ids
            total_reserved = sum(move_lines.mapped("quantity"))
            if total_reserved and demand:
                # Scale existing reserved lines; never exceed reserved qty.
                scale = min(1.0, demand / total_reserved)
                for line in move_lines:
                    line.quantity = line.quantity * scale
                # Only mark picked when we actually filled the reserved
                # lines. With zero reservations (consumables / unreserved
                # MTO moves) leaving picked=False lets
                # _auto_consume_non_tracked_components() fill the full
                # demand at finish; marking picked here with qty 0 would
                # cause the component to be consumed as 0 (move cancelled
                # after the Consumption Warning confirmation).
                move.picked = True
            consumed = sum(move_lines.mapped("quantity"))
            if move.product_uom.compare(consumed, demand) >= 0:
                filled += 1
            else:
                partial += 1
        self._clean_values()
        self._set_message(
            "info",
            _("Components auto-filled: %(filled)s full, %(partial)s partial.")
            % {"filled": filled, "partial": partial},
        )
        return True

    def _scan_lot(self, barcode):
        if not self.product_id or self.product_id.tracking == "none":
            return False
        lot_domain = [("name", "=", barcode)]
        if self.product_id:
            lot_domain.append(("product_id", "=", self.product_id.id))
        lots = self.env["stock.lot"].search(lot_domain)
        if not lots:
            # Not a lot of the current product -> TODO-A2 reverse lookup
            return self._scan_lot_fallback(barcode)
        if len(lots) > 1:
            self._set_message("more_match", _("Multiple lots found"))
            return True
        lot = lots
        self.lot_id = lot
        self.lot_name = lot.name
        self._compute_qty_available()
        self._set_message("info", _("Lot: %s. Enter qty and confirm.") % lot.name)
        self.step = 4
        self._set_message_step()
        return True

    # --- TODO-A2: lot reverse lookup ---
    def _scan_lot_fallback(self, barcode):
        """The scanned barcode is not a lot of the current product.

        Try to identify it before falling back to "create new lot":
          1. Global lot name search (company-scoped).
          2. Product barcode search (company-scoped).
        If a product is identified, resolve whether it is a component or the
        finished product of the current MO. If nothing matches, keep the
        current behavior of creating a new lot.
        """
        self.ensure_one()
        if not self.production_id or not self.company_id:
            return self._create_new_lot_flow(barcode)
        # Strategy 1: global lot name (company-scoped)
        lots = self.env["stock.lot"].search([
            ("name", "=", barcode),
            ("company_id", "=", self.company_id.id),
        ])
        if len(lots) > 1:
            self._set_message(
                "more_match",
                _("Multiple lots found for barcode: %s") % barcode,
            )
            return True
        if len(lots) == 1:
            return self._resolve_lot_owner(lots, lots.product_id)
        # Strategy 2: product barcode (company-scoped, allow shared products)
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
        # Neither lot nor product found -> keep current behavior
        return self._create_new_lot_flow(barcode)

    def _create_new_lot_flow(self, barcode):
        """Treat an unknown barcode as a new lot for the current product."""
        self.ensure_one()
        # TODO: confirm with business whether unknown lots should auto-create
        self.lot_name = barcode
        self.lot_id = False
        self.qty_available = 0.0
        self._set_message("info", _("New lot: %s. Enter qty and confirm.") % barcode)
        self.step = 4
        self._set_message_step()
        return True

    def _resolve_lot_owner(self, lot, product):
        """Identify whether `product` is a component or the finished product
        of the current MO and handle accordingly.

        - Finished product -> info prompt only (do NOT bind finished_lot_id).
        - Component of this MO -> switch product_id and bind the lot.
        - Unrelated product -> error.
        """
        self.ensure_one()
        if not self.production_id:
            self._set_message("error", _("No manufacturing order selected"))
            return True
        # Finished product -> prompt only, no binding, no step jump
        if product == self.production_id.product_id:
            self._set_message(
                "info",
                _("This is a finished product lot. "
                  "Enter/scan it in the finished lot area."),
            )
            return True
        # Component of this MO -> switch product and bind lot
        component_moves = self.production_id.move_raw_ids.filtered(
            lambda m: m.product_id == product and m.state != "cancel"
        )
        if component_moves:
            self.product_id = product
            self.product_uom_id = product.uom_id
            if lot:
                self.lot_id = lot
                self.lot_name = lot.name
                self._compute_qty_available()
                self._set_message(
                    "info", _("Lot: %s. Enter qty and confirm.") % lot.name
                )
                self.step = 4
            else:
                self.lot_id = False
                self.lot_name = False
                if product.tracking != "none":
                    self._set_message(
                        "info", _("Product: %s. Scan lot.") % product.name
                    )
                    self.step = 3
                else:
                    self._set_message(
                        "info",
                        _("Product: %s. Enter qty and confirm.") % product.name,
                    )
                    self.step = 4
            self._set_message_step()
            return True
        # Unrelated product
        self._set_message(
            "error",
            _("Lot belongs to product %(name)s which is not part of this MO")
            % {"name": product.name},
        )
        return True

    # --- TODO-A1: product fallback search ---
    def _scan_product_fallback(self, product):
        """Handle a scanned product that is NOT a component of the current MO.

        Three-tier fallback (scan-first, no confirmation dialogs):
          1. Product is a component of another active MO -> switch to it.
          2. Product is the finished product of any MO -> error.
          3. Otherwise -> offer to temporarily add & consume (non-tracked only).
        """
        self.ensure_one()
        # Branch 1: belongs to another active MO -> switch (no confirm)
        other_mos = self._find_other_mo_for_product(product)
        if other_mos:
            if len(other_mos) > 1:
                # Ambiguous: stash the current MO's in-progress scan, then
                # let the operator pick the target MO in the UI.
                self._stash_current_progress()
                self.product_id = False
                self.product_uom_id = False
                self.lot_id = False
                self.lot_name = False
                self.product_qty = 0.0
                self.pending_switch_production_ids = other_mos
                self.visible_switch_selector = True
                self._set_message(
                    "more_match",
                    _("Product %(name)s belongs to multiple MOs. Select one.")
                    % {"name": product.name},
                )
                return True
            # _switch_production sets the banner: notice + next instruction.
            self._switch_production(other_mos)
            return True
        # Branch 3: finished product of any MO -> cannot consume as component
        if self._is_any_mo_finished_product(product):
            self._set_message(
                "error",
                _("Product %(name)s is a finished product, cannot consume")
                % {"name": product.name},
            )
            return True
        # Branch 2: product exists but not reserved -> prompt to add
        self.product_id = product
        self.product_uom_id = product.uom_id
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 1.0
        self._compute_qty_available()
        self.visible_force_add = True
        self._set_message(
            "more_match",
            _("Product %(name)s is not in BOM. Force add to consume?")
            % {"name": product.name},
        )
        return True

    def _find_other_mo_for_product(self, product):
        """Return active MOs (other than current) that consume `product`."""
        self.ensure_one()
        if not self.production_id:
            return self.env["mrp.production"]
        return self.env["mrp.production"].search([
            ("id", "!=", self.production_id.id),
            ("state", "in", ("confirmed", "progress", "to_close")),
            ("move_raw_ids.product_id", "=", product.id),
        ])

    def _is_any_mo_finished_product(self, product):
        """True if `product` is the finished product of any MO."""
        return bool(self.env["mrp.production"].search_count(
            [("product_id", "=", product.id)], limit=1
        ))

    def _stash_current_progress(self):
        """Snapshot the uncommitted scan state of the current MO.

        Restored (and consumed) by _restore_progress when the operator
        switches back to this MO. Only wizards with actual in-progress
        scans (a component or a finished lot already scanned) are stashed.
        """
        self.ensure_one()
        mo = self.production_id
        if not mo or not (self.product_id or self.finished_lot_id):
            return
        stash = dict(self.scan_progress_stash or {})
        stash[str(mo.id)] = {
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "lot_id": self.lot_id.id,
            "lot_name": self.lot_name,
            "product_qty": self.product_qty,
            "finished_lot_id": self.finished_lot_id.id,
            "finished_lot_name": self.finished_lot_name,
            "finished_qty_producing": self.finished_qty_producing,
            "location_id": self.location_id.id,
            "step": self.step,
            "visible_force_done": self.visible_force_done,
            "visible_force_add": self.visible_force_add,
            "manual_entry": self.manual_entry,
        }
        self.scan_progress_stash = stash

    def _switch_production(self, new_mo):
        """Switch the wizard to `new_mo`, discarding all current scan progress.

        Uncommitted scan state of the previous MO is stashed first
        (TODO-B3 restores it on return). Field reset is explicit (not
        relying on onchange) so no stale state from the previous MO leaks
        into the new context. Any ambiguous-MO candidate list is cleared.
        """
        self.ensure_one()
        # Stash before changing production_id (B3 restores on return).
        if self.production_id and self.production_id != new_mo:
            self._stash_current_progress()
        # --- MO context ---
        self.production_id = new_mo
        self.workorder_id = False
        # --- Finished-lot scan state ---
        self.finished_lot_id = False
        self.finished_lot_name = False
        self.finished_qty_producing = new_mo.product_qty
        # --- Component scan state ---
        self.product_id = False
        self.product_uom_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.location_id = new_mo.location_src_id
        # --- Flags & misc ---
        self.visible_force_done = False
        self.visible_force_add = False
        self.manual_entry = False
        self.barcode = False
        self.res_model_id = self.env.ref("mrp.model_mrp_production").id
        self.res_id = new_mo.id
        # Clear the ambiguous-MO selector so it does not linger on screen.
        self.pending_switch_production_ids = [(5, 0, 0)]
        self.visible_switch_selector = False
        # Restore uncommitted scan state previously stashed for the new MO;
        # only fall back to plain defaults when nothing was stashed.
        if not self._restore_progress(new_mo):
            self._set_default_values()
        # Single banner message: switch notice + next scan instruction.
        # Callers must NOT overwrite it with their own "Switched" text,
        # otherwise the restored/derived instruction would be lost.
        self._set_message(
            "info",
            _("Switched to MO %(mo)s. %(next)s")
            % {"mo": new_mo.name, "next": self.message},
        )

    def _restore_progress(self, mo):
        """Restore uncommitted scan state stashed for `mo`.

        The stash entry is consumed (deleted) on restore, so a second
        arrival without new scans starts from plain defaults. Returns True
        when a snapshot was restored, False when there was none.
        """
        self.ensure_one()
        stash = dict(self.scan_progress_stash or {})
        snapshot = stash.pop(str(mo.id), None)
        if not snapshot:
            return False
        self.scan_progress_stash = stash
        # Finished-lot state
        self.finished_lot_id = snapshot.get("finished_lot_id") or False
        self.finished_lot_name = snapshot.get("finished_lot_name") or False
        if snapshot.get("finished_qty_producing"):
            self.finished_qty_producing = snapshot["finished_qty_producing"]
        # Component scan state
        self.product_id = snapshot.get("product_id") or False
        self.product_uom_id = snapshot.get("product_uom_id") or False
        self.lot_id = snapshot.get("lot_id") or False
        self.lot_name = snapshot.get("lot_name") or False
        self.product_qty = snapshot.get("product_qty") or 0.0
        self.location_id = snapshot.get("location_id") or mo.location_src_id
        # Visibility / mode flags
        self.visible_force_done = bool(snapshot.get("visible_force_done"))
        self.visible_force_add = bool(snapshot.get("visible_force_add"))
        self.manual_entry = bool(snapshot.get("manual_entry"))
        # NB: step 0 (finished-lot scan) is valid; do NOT use `or 1`,
        # which would coerce a stored 0 back to 1.
        step = snapshot.get("step")
        self.step = step if step is not None else 1
        # Recompute availability for the restored product/lot/location
        if self.product_id:
            self._compute_qty_available()
        self._set_message_step()
        return True

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
        groups = self.env["stock.quant"].read_group(
            domain, ["quantity"], [], orderby="id"
        )
        self.qty_available = groups[0]["quantity"] if groups else 0.0

    # --- Action methods ---
    def action_confirm(self):
        """Confirm the scanned component and update stock move lines."""
        # Edge case: MO state check
        if self.production_state == "draft":
            self._set_message(
                "error", _("MO is draft, confirm it before scanning")
            )
            return False
        if self.production_state in ("done", "cancel"):
            self._set_message(
                "error",
                _("MO is %(state)s, cannot scan components") % {"state": self.production_state},
            )
            return False
        if not self.product_id:
            self._set_message("error", _("No product scanned"))
            return False
        if not self.location_id:
            self._set_message("error", _("No source location scanned"))
            return False
        if self.product_id.tracking != "none" and not self.lot_id and not self.lot_name:
            self._set_message("error", _("Lot required for tracked product"))
            return False
        if not self.product_qty or self.product_qty <= 0:
            self._set_message("error", _("Quantity must be positive"))
            return False

        # Process lot creation if needed
        if not self.lot_id and self.lot_name and self.product_id.tracking != "none":
            self.lot_id = self._create_new_lot()

        move_dic = self._process_stock_move_line()
        if move_dic:
            self._set_message("success", _("Component scanned: %(prod)s x%(qty)s")
                              % {"prod": self.product_id.name, "qty": self.product_qty})
            self._clean_values()
            return move_dic
        return False

    def _process_stock_move_line(self):
        """Find matching raw material move and update/create move line.

        In Odoo 19, stock.move.line.quantity is pre-filled to the reserved
        amount after _action_assign. We SET (not ADD) the scanned quantity
        on matching move lines, and create new ones only when no match found.
        """
        self.ensure_one()
        if not self.production_id:
            return False
        moves = self.production_id.move_raw_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state != "cancel"
        )
        if not moves:
            self._set_message(
                "error",
                _("Product %(name)s is not a component of this MO")
                % {"name": self.product_id.name},
            )
            return False

        # Find destination location (production virtual location)
        dest_location = self.product_id.with_company(
            self.production_id.company_id
        ).property_stock_production

        # Find existing move lines matching our product/location/lot criteria
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
            # SET semantics: matching line quantity is replaced, but quantities
            # already allocated to OTHER (different lot/location) lines count.
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
            # If the reservation was split across several matching lines,
            # absorb the increase from the other matching lines so the SET
            # does not push the total above demand (they shrink/unlink).
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
            move_lines_dic[line.move_id.id] = line
        else:
            # New line (e.g. consuming a different lot than the reserved one).
            # Redistribute demand from other lines so a lot substitution does
            # not silently double consumption (mirrors enterprise _find_quant
            # behaviour). Only the un-absorbable excess requires force.
            excess = other_lines_qty + self.product_qty - total_demand
            if excess > 0:
                for line in other_lines.sorted(key=lambda l: l.id):
                    take = min(line.quantity, excess)
                    line.quantity = line.quantity - take
                    excess -= take
                    if float_is_zero(line.quantity,
                                     precision_rounding=rounding):
                        line.unlink()
                    if excess <= 0:
                        break
            if (
                excess > 0
                and not force
            ):
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
                "location_dest_id": dest_location.id,
                "lot_id": self.lot_id.id if self.lot_id else False,
                "lot_name": self.lot_id.name if self.lot_id else self.lot_name or False,
            }
            new_line = self.env["stock.move.line"].create(sml_vals)
            move_lines_dic[move.id] = new_line

        return move_lines_dic

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

    def action_force_done(self):
        return self.with_context(force_create_move=True).action_confirm()

    def action_force_add(self):
        """Temporarily add a non-BOM, non-tracked product as a raw material
        and consume the scanned quantity.

        Reuses `_process_stock_move_line` for the actual consumption logic.
        Tracked products are out of scope (follow-up TODO).
        """
        self.ensure_one()
        if not self.production_id or not self.product_id:
            self._set_message("error", _("No product to add"))
            return False
        if self.product_id.tracking != "none":
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
        # Create the raw material move on the MO
        dest_location = self.product_id.with_company(
            self.production_id.company_id
        ).property_stock_production
        move = self.env["stock.move"].create({
            "name": self.product_id.name,
            "product_id": self.product_id.id,
            "product_uom_qty": self.product_qty,
            "product_uom": self.product_uom_id.id or self.product_id.uom_id.id,
            "production_id": self.production_id.id,
            "raw_material_production_id": self.production_id.id,
            "location_id": self.location_id.id,
            "location_dest_id": dest_location.id,
        })
        move._action_confirm()
        # Consume via existing logic
        move_dic = self._process_stock_move_line()
        if move_dic:
            self.visible_force_add = False
            self._set_message(
                "success",
                _("Added & consumed: %(prod)s x%(qty)s")
                % {"prod": self.product_id.name, "qty": self.product_qty},
            )
            self._clean_values()
            return move_dic
        return False

    def action_apply_finished_lot(self):
        """Apply the scanned finished lot and qty_producing to the MO."""
        if not self.production_id:
            return False
        # Create new lot if needed
        lot = self.finished_lot_id
        if not lot and self.finished_lot_name:
            lot = self._create_new_finished_lot()
        if not lot and self.production_id.product_id.tracking != "none":
            self._set_message("error", _("Finished lot required for tracked product"))
            return False
        if not self.finished_qty_producing or self.finished_qty_producing <= 0:
            self._set_message("error", _("Quantity to produce must be positive"))
            return False
        vals = {"qty_producing": self.finished_qty_producing}
        if lot:
            # Guard: the m2o picker can no longer be domain-restricted
            # client-side, so reject a lot belonging to another product.
            if lot.product_id != self.production_id.product_id:
                self._set_message(
                    "error",
                    _("Lot %(lot)s belongs to %(product)s, not to the "
                      "finished product")
                    % {
                        "lot": lot.name,
                        "product": lot.product_id.display_name,
                    },
                )
                return False
            # Replace (not append): core constrains lot-tracked products to
            # max 1 lot in lot_producing_ids, re-applying a different lot
            # with (4, id) would raise "You cannot set more than 1 lot".
            vals["lot_producing_ids"] = [(6, 0, [lot.id])]
        self.production_id.write(vals)
        self._set_message(
            "success",
            _("Finished lot: %(lot)s, qty: %(qty)s applied to MO")
            % {"lot": lot.name if lot else _("N/A"), "qty": self.finished_qty_producing},
        )
        # Move to step 1 (scan source location)
        self.step = 1
        self._set_message_step()
        return True

    def _auto_consume_non_tracked_components(self):
        """Scale non-tracked, auto-consumed components to qty_producing.

        Only raw moves that are ALL of:
          * product tracked as 'none'
          * manual_consumption = False
          * not already picked (i.e. no explicit scan / edit)
        are scaled. Already scanned moves are skipped so explicit lines are
        never overwritten. The formula mirrors core _set_qty_producing:
        new_qty = (qty_producing - qty_produced) * unit_factor.
        """
        self.ensure_one()
        production = self.production_id
        if not production:
            return
        auto_moves = production.move_raw_ids.filtered(
            lambda m: (
                m.state not in ("done", "cancel")
                and m.product_id.tracking == "none"
                and not m.manual_consumption
                and not m.picked
            )
        )
        for move in auto_moves:
            new_qty = move.product_uom.round(
                (production.qty_producing - production.qty_produced)
                * move.unit_factor
            )
            # Core-identical write: replaces the move lines, drops reservation
            move._set_quantity_done(new_qty)
            if new_qty:
                move.picked = True

    def action_finish_production(self):
        """Finish production: auto-applies any pending finished_lot_name
        (building the lot if needed) before calling button_mark_done.

        Do NOT remove the auto-apply step (lot creation + lot_producing_ids
        write below) without updating the OWL Apply Lot button visibility
        logic — the two share the same lot binding semantics.

        Mirrors core button_mark_done: consumption/backorder wizard actions
        are returned to the client for the user to resolve; a plain True
        means the MO is done.
        """
        if not self.production_id:
            self._set_message("error", _("No manufacturing order"))
            return False
        if self.production_state not in ("confirmed", "progress", "to_close"):
            self._set_message(
                "error",
                _("MO is %(state)s, cannot finish production")
                % {"state": self.production_state},
            )
            return False
        # Apply scanned finished lot before marking done
        lot = self.finished_lot_id
        if not lot and self.finished_lot_name:
            lot = self._create_new_finished_lot()
        if (
            self.production_id.product_id.tracking != "none"
            and not lot
            and not self.production_id.lot_producing_ids
        ):
            self._set_message(
                "error",
                _("Please scan the finished product serial number (SN) first, "
                  "or use Manual Entry."),
            )
            return False
        qty = self.finished_qty_producing or self.production_id.qty_producing
        if not qty or qty <= 0:
            self._set_message("error", _("Quantity to produce must be positive"))
            return False
        vals = {"qty_producing": qty}
        if lot:
            # Replace semantics: core allows max 1 lot for lot-tracked products
            vals["lot_producing_ids"] = [(6, 0, [lot.id])]
        self.production_id.write(vals)
        # Scale not-yet-scanned non-tracked auto moves before the core
        # consumption check (explicit scanned lines are never touched).
        self._auto_consume_non_tracked_components()
        result = self.production_id.with_context(
            skip_redirection=True
        ).button_mark_done()
        if result is True:
            self._set_message("success", _("Production done: %s") % self.production_id.name)
            return True
        # D3: dialog path (consumption warning / backorder). Stash the
        # pending_finish flag so _onchange_production_state can flip this
        # placeholder to a real "Production done" success banner once
        # the dialog closes and the client reloads the record. The
        # placeholder banner stays visible while the user resolves the
        # dialog; if the user cancels, the MO stays progress and the
        # placeholder stays (still pointing to the unresolved dialog).
        self.pending_finish = True
        self._set_message(
            "info",
            _("Resolving consumption warning for %s...") % self.production_id.name,
        )
        # Consumption / backorder wizard action: let the client open it
        return result

    def _create_new_finished_lot(self):
        """Create a new lot for the finished product."""
        if not self.finished_lot_name or not self.production_id:
            return False
        finished_product = self.production_id.product_id
        existing = self.env["stock.lot"].search([
            ("name", "=", self.finished_lot_name),
            ("product_id", "=", finished_product.id),
        ])
        if existing:
            self.finished_lot_id = existing
            return existing
        new_lot = self.env["stock.lot"].create({
            "name": self.finished_lot_name,
            "product_id": finished_product.id,
            "company_id": self.company_id.id if self.company_id else self.env.company.id,
        })
        self.finished_lot_id = new_lot
        return new_lot

    def action_clean_finished_lot(self):
        """Clear the scanned finished lot."""
        self.finished_lot_id = False
        self.finished_lot_name = False
        if self.production_id and self.production_id.product_id.tracking != "none":
            self.step = 0
        else:
            self.step = 1
        self._set_message_step()

    def action_manual_entry(self):
        self.manual_entry = not self.manual_entry
        return True

    def action_clean_lot(self):
        self.lot_id = False
        self.lot_name = False
        self._set_message_step()

    def action_clean_product(self):
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.visible_force_add = False
        self._set_message_step()

    def _clean_values(self):
        """Clean scanned values after successful confirmation."""
        self.product_id = False
        self.lot_id = False
        self.lot_name = False
        self.product_qty = 0.0
        self.qty_available = 0.0
        self.visible_force_done = False
        self.visible_force_add = False
        self.step = 2
        self._set_message_step()

    def action_back(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "mrp.mrp_production_action"
        )

    def action_open_production(self):
        self.ensure_one()
        if self.production_id:
            return self.production_id.get_formview_action()

    # --- Message helpers ---
    def _set_message(self, message_type, message):
        self.message_type = message_type
        self.message = message

    def _get_step_message(self):
        """Context-aware scan instruction for the current step (TODO-C2).

        Always states WHAT to scan next and for which product/MO, so the
        text stays meaningful after a progress restore (_restore_progress
        re-runs _set_message_step and the banner reflects the restored
        step automatically).
        """
        self.ensure_one()
        if self.step == 0:
            return _("Scan the finished product lot: %s") % (
                self.production_product_id.display_name
            )
        if self.step == 1:
            return _("MO %s: scan source location %s or scan a component") % (
                self.production_id.name, self.location_id.name,
            )
        if self.step == 2:
            return _("Scan a component of MO %s") % self.production_id.name
        if self.step == 3:
            return _("Scan the lot/serial of %s") % self.product_id.name
        if self.step == 4:
            return _("Enter the quantity for %s") % self.product_id.name
        return ""

    def _set_message_step(self):
        steps = {
            0: _("Scan finished product lot"),
            1: _("Scan source location (or scan component directly)"),
            2: _("Scan component product"),
            3: _("Scan lot/serial"),
            4: _("Enter quantity and confirm"),
        }
        # Static short hint kept verbatim (tests assert it exactly).
        self.message_step = steps.get(self.step, "")
        # TODO-C2: dynamic instruction for the banner.
        self._set_message("info", self._get_step_message())
