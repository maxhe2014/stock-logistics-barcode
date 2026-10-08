// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { Component, useState, onWillStart, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * PickingScanApp — thin OWL client action for the outgoing-picking
 * barcode scan flow.
 *
 * Thin-shell pattern (same as MrpScanApp): the client action is a UI
 * shell over the wizard backend. Barcodes (hardware scanner via the
 * global barcode_service bus, or manual input) go through a single RPC
 * ``process_barcode_and_dispatch(barcode)`` → ``{action, state}``.
 * Action RPCs (confirm, consume, validate, force-add) are separate
 * calls; their three-state return values are handled by
 * ``_handleActionResult``.
 *
 * Dependencies (CE, LGPL-compatible): ``barcodes``, ``stock``, ``web``,
 * ``owl``. No enterprise modules referenced.
 */
export class PickingScanApp extends Component {
    static template = "stock_barcodes_picking.PickingScanApp";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode");
        // Global keyboard scanner: any barcode_scanned event from the CE
        // barcode service triggers _onScan. Covers hardware scanners and
        // the mobile camera scanner alike.
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
            this._onScan(ev.detail.barcode)
        );

        this.wizId = this.props.action.params?.wiz_id;
        // Local UI mirror of the wizard state. Hydrated from
        // ``get_scan_state()`` after every interaction; rendered by the
        // t-* directives in the template.
        this.state = useState({
            message: "",
            message_type: "info",
            picking_id: false,
            picking_name: "",
            picking_state: "",
            picking_type_code: "",
            location_id: false,
            location_name: "",
            location_dest_id: false,
            location_dest_name: "",
            product_id: false,
            product_name: "",
            product_tracking: "none",
            product_uom_name: "",
            lot_id: false,
            lot_name: "",
            product_qty: 0,
            qty_available: 0,
            total_demand: 0,
            total_done: 0,
            visible_force_done: false,
            visible_force_add: false,
            visible_switch_selector: false,
            pending_switch_pickings: [],
            active_move_id: false,
            active_move_product_name: "",
            scan_steps: [],
            step: 0,
            move_ids: [],
            scanning: false,
            // Local UI state (not from backend)
            last_unmatched_barcode: "",
            editingQtyMoveId: false,
            draftQty: "",
            // Multi-SN accordion: the move id whose lot list is expanded,
            // or false when all are collapsed (default).
            expandedMoveId: false,
            // Move id to scroll into view after the next render patch.
            pendingScrollMoveId: false,
        });

        // Sound alert for scan errors. Only an error tone is used
        // (success is silent). Preloaded so the first error plays
        // without a network round-trip.
        this.soundKo = new Audio(
            "/stock_barcodes_picking/static/src/sounds/error.wav"
        );

        onWillStart(async () => {
            await this._refreshState();
        });

        // After every render patch, if a scan asked us to jump to a move
        // row, scroll it into the middle of the move-list viewport.
        // Uses direct (non-smooth) scrolling for fast scanner response.
        onPatched(() => {
            const moveId = this.state.pendingScrollMoveId;
            if (!moveId) {
                return;
            }
            this.state.pendingScrollMoveId = false;
            const el = document.querySelector(
                `[data-move-row="${moveId}"]`
            );
            if (el && el.scrollIntoView) {
                el.scrollIntoView({ block: "center", inline: "nearest" });
            }
        });
    }

    /**
     * Refresh `this.state` from the server-side wizard snapshot.
     * Used at start and after any backend interaction.
     */
    async _refreshState() {
        const snapshot = await this.orm.call(
            "wiz.stock.barcodes.picking",
            "get_scan_state",
            [[this.wizId]]
        );
        Object.assign(this.state, snapshot);
        this._enrichMoves();
    }

    /**
     * Add a `pickedLots` filtered array to each move so the template can
     * distinguish picked (scanned) lots from reserved (unpicked) ones.
     * Must be called after every state assignment from the backend.
     */
    _enrichMoves() {
        for (const mv of (this.state.move_ids || [])) {
            mv.pickedLots = (mv.lots || []).filter((l) => l.picked);
        }
    }

    /**
     * Play the error sound.
     *
     * Triggered for error-class outcomes: message_type in
     * {error, not_found, more_match}, and for RPC exceptions.
     * Success is silent by design.
     */
    _playAlert() {
        try {
            this.soundKo.currentTime = 0;
            this.soundKo.play().catch(() => {});
        } catch (_e) {
            /* audio element not ready */
        }
    }

    /**
     * Core scan handler — single RPC entry.
     * Calls process_barcode_and_dispatch(barcode) → {action, state}.
     * Tracks the last unmatched barcode so the "Force add?" button can
     * pass it back to action_force_add_from_barcode.
     */
    async _onScan(barcode) {
        if (!barcode || this.state.scanning) {
            return;
        }
        // When the candidate selector is open, the manual input is
        // disabled, but the hardware scanner can still fire. Let the
        // scan through — the backend guard only accepts picking-name
        // scans while the selector is open, and rejects everything else.
        this.state.scanning = true;
        // Snapshot each move's picked-lot count before the scan so we can
        // detect which move received a new picked lot afterward (for scroll).
        const pickedCountBefore = {};
        for (const mv of this.state.move_ids) {
            pickedCountBefore[mv.id] = (mv.pickedLots || []).length;
        }
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "process_barcode_and_dispatch",
                [[this.wizId], barcode]
            );
            Object.assign(this.state, res.state);
            this._enrichMoves();
            // Error-class scan result → sound alert.
            if (["error", "not_found", "more_match"].includes(this.state.message_type)) {
                this._playAlert();
            }
            // Scroll to the move that gained a picked lot (quick jump).
            let scannedMoveId = false;
            for (const mv of this.state.move_ids) {
                const before = pickedCountBefore[mv.id] || 0;
                const after = (mv.pickedLots || []).length;
                if (after > before) {
                    scannedMoveId = mv.id;
                    break;
                }
            }
            if (scannedMoveId) {
                this.state.pendingScrollMoveId = scannedMoveId;
            }
            // Remember the barcode when it was not found, so the
            // operator can force-add it. Clear on any other outcome.
            if (this.state.message_type === "not_found") {
                this.state.last_unmatched_barcode = barcode;
            } else {
                this.state.last_unmatched_barcode = "";
            }
            if (res.action) {
                await this.actionService.doAction(res.action, {
                    onClose: () => this._refreshState(),
                });
            }
        } catch (err) {
            this.notification.add(
                _t("Scan failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Enter on the manual input box: re-route to _onScan. */
    onManualScanEnter(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const value = ev.currentTarget.value.trim();
        if (value) {
            this._onScan(value);
            ev.currentTarget.value = "";
        }
    }

    /** Back button — return to the previous controller (the picking list). */
    onBack() {
        this.env.config.historyBack();
    }

    /**
     * Unified three-state handler for action RPCs.
     *
     * Action methods return one of:
     *   - false: guard blocked it / validation error → show error, no action
     *   - true:  success, no dialog → refresh state
     *   - dict:  a dialog action (e.g. backorder wizard) → doAction with
     *            onClose refresh
     *
     * We MUST branch on all three; `if (res) doAction(res)` would silently
     * swallow the false (guard) case.
     */
    async _handleActionResult(res, errorLabel) {
        if (res === false) {
            // Guard or validation error — the backend sets the message;
            // refresh so the UI shows it.
            await this._refreshState();
            if (["error", "not_found", "more_match"].includes(this.state.message_type)) {
                this._playAlert();
            }
            return;
        }
        if (res && typeof res === "object" && res.type) {
            await this.actionService.doAction(res, {
                onClose: () => this._refreshState(),
            });
            return;
        }
        // true or any non-action value
        await this._refreshState();
    }

    /**
     * Call a no-arg wizard action method and route its three-state
     * return through _handleActionResult.
     */
    async _callAction(methodName, errorLabel) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                methodName,
                [[this.wizId]]
            );
            await this._handleActionResult(res, errorLabel || methodName);
        } catch (err) {
            this.notification.add(
                _t("%(label)s failed: %(err)s", {
                    label: errorLabel || methodName,
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Confirm the scanned product (qty step). */
    onConfirm() {
        return this._callAction("action_confirm", _t("Confirm"));
    }

    /** Force-confirm (allow over-reserved / over-demand quantity). */
    onForceDone() {
        return this._callAction("action_force_done", _t("Force Consume"));
    }

    /**
     * Click a move row to preselect the target move.
     * Narrow subsequent lot/qty scans to this move.
     */
    async onSelectMove(moveId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        try {
            const ok = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "set_active_move",
                [[this.wizId], moveId]
            );
            if (ok) {
                await this._refreshState();
            }
        } catch (err) {
            this.notification.add(
                _t("Select row failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
            this._playAlert();
        }
    }

    /** Enter inline quantity-edit mode for a move row (pencil button).
     *  Pre-fills the draft with the move demand. */
    onEditMoveQty(moveId) {
        const mv = this.state.move_ids.find((m) => m.id === moveId);
        if (!mv) {
            return;
        }
        this.state.editingQtyMoveId = moveId;
        this.state.draftQty = String(mv.product_uom_qty || 0);
    }

    onDraftQtyInput(ev) {
        this.state.draftQty = ev.currentTarget.value;
    }

    onDraftQtyKeydown(ev, moveId) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmMoveQty(moveId);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.onCancelMoveQty();
        }
    }

    /**
     * Pencil-button sequence: prompt qty FIRST (done by the inline
     * input), then on confirm: set_active_move(moveId) →
     * action_consume_with_qty(qty). Two RPCs, one user action. If the
     * user cancels the input, no RPC fires (active_move_id untouched).
     */
    async onConfirmMoveQty(moveId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        const qty = parseFloat(this.state.draftQty);
        if (!qty || qty <= 0) {
            this.notification.add(_t("Please enter a positive quantity"), {
                type: "danger",
            });
            this._playAlert();
            return;
        }
        this.state.scanning = true;
        try {
            // 1. Bind the target move
            const ok = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "set_active_move",
                [[this.wizId], moveId]
            );
            if (!ok) {
                await this._refreshState();
                this._playAlert();
                return;
            }
            // 2. Consume with the entered quantity
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_consume_with_qty",
                [[this.wizId], qty]
            );
            await this._handleActionResult(res, "Consume");
            this.state.editingQtyMoveId = false;
            this.state.draftQty = "";
        } catch (err) {
            this.notification.add(
                _t("Consume with quantity failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    onCancelMoveQty() {
        this.state.editingQtyMoveId = false;
        this.state.draftQty = "";
    }

    /**
     * Remove a scanned lot/SN from a move. Used by the trash button on
     * each lot badge so the operator can correct a mis-scanned serial
     * without leaving the scan flow.
     */
    async onRemoveMoveLot(moveId, lotId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        try {
            await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_remove_move_lot",
                [[this.wizId], moveId, lotId]
            );
            await this._refreshState();
        } catch (err) {
            this.notification.add(
                _t("Remove lot failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        }
    }

    /**
     * Accordion toggle for a move's multi-SN list. Opening one move
     * collapses any other. Clicking the already-open move collapses it.
     */
    onToggleMoveLots(moveId) {
        if (this.state.expandedMoveId === moveId) {
            this.state.expandedMoveId = false;
        } else {
            this.state.expandedMoveId = moveId;
        }
    }

    /**
     * One-click consume the full demand of the active/non-tracked
     * product. Tracked products are rejected server-side.
     */
    onConsumeByDemand() {
        return this._callAction(
            "action_consume_by_demand",
            _t("Consume by demand")
        );
    }

    /**
     * Put all picked (unpacked) lines into a new package.
     */
    onPutInPack() {
        return this._callAction(
            "action_put_in_pack",
            _t("Put in Pack")
        );
    }

    /**
     * Validate the picking. Three-state:
     *   false → guard / no picking → show error
     *   true  → validated, no backorder → refresh
     *   dict  → backorder wizard → doAction + onClose refresh
     */
    onValidatePicking() {
        return this._callAction(
            "action_validate_picking",
            _t("Validate")
        );
    }

    /**
     * Force-add the last unmatched barcode as a new move line.
     * The frontend never RPCs product search — the server resolves the
     * product from the barcode (single source of truth).
     */
    async onForceAddFromBarcode() {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        const barcode = this.state.last_unmatched_barcode;
        if (!barcode) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_force_add_from_barcode",
                [[this.wizId], barcode]
            );
            await this._handleActionResult(res, "Force add");
            this.state.last_unmatched_barcode = "";
        } catch (err) {
            this.notification.add(
                _t("Force add failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /**
     * Pick one of the candidate pickings from the multi-match selector.
     * Calls select_picking_candidate(id) which switches and closes the
     * selector.
     */
    async onSelectPickingCandidate(pickingId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const ok = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "select_picking_candidate",
                [[this.wizId], pickingId]
            );
            if (ok) {
                await this._refreshState();
            } else {
                await this._refreshState();
            }
        } catch (err) {
            this.notification.add(
                _t("Select transfer failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    // --- Computed getters for template visibility ---

    /** Map message_type → alert CSS class. */
    get alertClass() {
        const t = this.state.message_type || "info";
        return {
            info: "alert-info",
            success: "alert-success",
            warning: "alert-warning",
            error: "alert-danger",
            not_found: "alert-danger",
            more_match: "alert-warning",
        }[t] || "alert-info";
    }

    /** Confirm button visible: a product is scanned and we are at/after
     *  the qty step with a positive quantity. */
    get canConfirm() {
        return (
            !!this.state.picking_id &&
            !!this.state.product_id &&
            (this.state.product_qty || 0) > 0
        );
    }

    /** Validate button: picking exists and is in a validatable state. */
    get canValidate() {
        return (
            !!this.state.picking_id &&
            !["draft", "done", "cancel"].includes(this.state.picking_state)
        );
    }

    /** Consume-by-demand: non-tracked product is active. */
    get canConsumeByDemand() {
        return (
            !!this.state.picking_id &&
            !!this.state.product_id &&
            this.state.product_tracking === "none"
        );
    }

    /**
     * Put in Pack: visible when the user has the packages group and there
     * is at least one picked (unpacked) move line.
     */
    get canPutInPack() {
        if (!this.state.show_put_in_pack || !this.state.picking_id) {
            return false;
        }
        const moves = this.state.move_ids || [];
        return moves.some((mv) => (mv.pickedLots || []).length > 0);
    }

    /** Step label for the current step index. */
    get currentStepLabel() {
        const steps = this.state.scan_steps || [];
        const s = steps[this.state.step];
        return s ? s.label : "";
    }
}

registry
    .category("actions")
    .add("stock_barcodes_picking.PickingScanApp", PickingScanApp);
