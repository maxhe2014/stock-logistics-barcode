// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * MrpScanApp — thin OWL client action for the MRP scan flow.
 *
 * Route B1 (薄壳): the client action is a thin shell over the existing
 * wizard backend. The operator scans a barcode (via the global
 * barcode_service keyboard listener) or types it manually; the client
 * makes a single RPC to `wiz.stock.barcodes.mrp.process_barcode_and_dispatch`
 * which runs the existing `_process_barcode` logic server-side and
 * returns `{action, state}`. If `action` is non-null (multi-match
 * case), `action.doAction` is called to auto-open the filtered
 * mrp.production list — no extra button click (the onchange
 * can't-return-action trade-off is gone).
 *
 * Dependencies (CE, LGPL-compatible): `barcodes`, `web`, `owl`.
 * No OEEL/enterprise modules referenced.
 */
export class MrpScanApp extends Component {
    static template = "stock_barcodes_mrp.MrpScanApp";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode");
        // Global keyboard scanner: any barcode_scanned event from the
        // CE barcode service triggers _onScan. This covers hardware
        // scanners and the mobile camera scanner alike.
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
            this._onScan(ev.detail.barcode)
        );

        this.wizId = this.props.action.params?.wiz_id;
        // Local UI mirror of the wizard state. Hydrated from
        // `get_scan_state()` after every scan; rendered by the
        // t-* directives in the template.
        this.state = useState({
            step: 0,
            message: "",
            message_type: "info",
            message_step: "",
            production_id: false,
            production_name: "",
            production_product_name: "",
            location_name: "",
            product_name: "",
            lot_name: "",
            finished_qty_producing: 0,
            visible_switch_selector: false,
            components: [],
            scanning: false,
            // Button-visibility fields (returned by get_scan_state)
            production_state: "",
            finished_product_tracking: "none",
            product_id: false,
            product_tracking: "none",
            product_qty: 0,
            lot_id: false,
            lot_name_raw: "",
            finished_lot_id: false,
            finished_lot_name: "",
            visible_force_done: false,
        });

        onWillStart(async () => {
            // First render: fetch the initial wizard state so the UI
            // shows the right step banner even before any scan.
            await this._refreshState();
        });
    }

    /**
     * Refresh `this.state` from the server-side wizard snapshot.
     * Used at start and after any backend interaction.
     */
    async _refreshState() {
        const snapshot = await this.orm.call(
            "wiz.stock.barcodes.mrp",
            "get_scan_state",
            [[this.wizId]]
        );
        Object.assign(this.state, snapshot);
    }

    /**
     * Core scan handler — single RPC entry.
     * Calls process_barcode_and_dispatch(barcode) → {action, state}.
     * If action is non-null, auto-doAction into the filtered MO list.
     */
    async _onScan(barcode) {
        if (!barcode || this.state.scanning) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.mrp",
                "process_barcode_and_dispatch",
                [[this.wizId], barcode]
            );
            Object.assign(this.state, res.state);
            if (res.action) {
                // Multi-match: auto-open the filtered MO list.
                // No extra button click — the onchange trade-off is gone.
                this.actionService.doAction(res.action);
            }
        } catch (err) {
            this.notification.add(
                _t("Scan failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
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

    /** Back button — return to the previous controller (the MO list). */
    onBack() {
        this.env.config.historyBack();
    }

    /**
     * Dual-path: explicit "View candidate MOs" button — kept as a
     * fallback for cases where the auto-doAction path was skipped
     * (e.g. operator cancelled the list). Same backend method.
     */
    async onViewCandidates() {
        try {
            const action = await this.orm.call(
                "wiz.stock.barcodes.mrp",
                "action_open_candidate_list",
                [[this.wizId]]
            );
            if (action) {
                this.actionService.doAction(action);
            }
        } catch (err) {
            this.notification.add(
                _t("Open candidates failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
        }
    }

    /** Map message_type → alert CSS class for the message bar. */
    get alertClass() {
        const t = this.state.message_type || "info";
        return {
            info: "alert-info",
            success: "alert-success",
            warning: "alert-warning",
            error: "alert-danger",
            not_found: "alert-danger",
        }[t] || "alert-info";
    }

    /**
     * 5-step progress badges (mirrors the legacy wizard form stepbar).
     * State is derived purely from state.step + tracking fields; done/current
     * use the same step comparison as the old form. Hidden for steps that
     * don't apply (e.g. Finished Lot for untracked products).
     */
    get stepBadges() {
        const step = this.state.step || 0;
        const finTrack = this.state.finished_product_tracking || "none";
        const compTrack = this.state.product_tracking || "none";
        const badges = [
            {
                key: "finished",
                label: "Finished Lot",
                done: step > 0,
                current: step === 0,
                hidden: finTrack === "none",
            },
            {
                key: "location",
                label: "Location",
                done: step > 1,
                current: step === 1,
                hidden: false,
            },
            {
                key: "component",
                label: "Component",
                done: step > 2,
                current: step === 2,
                hidden: false,
            },
            {
                key: "lot",
                label: "Lot / SN",
                done: step > 3,
                current: step === 3,
                hidden: compTrack === "none",
            },
            {
                key: "qty",
                label: "Qty",
                done: step > 4,
                current: step === 4,
                hidden: false,
            },
        ];
        for (const b of badges) {
            b.cls = b.done
                ? "bg-success"
                : b.current
                ? "bg-primary"
                : "bg-secondary opacity-50";
        }
        return badges;
    }

    /** Apply Lot visible: tracked finished product + a lot is pending/selected
     *  + positive qty. Mirrors action_apply_finished_lot guards (no step check —
     *  the backend does not enforce step, and after scanning the product/SN the
     *  wizard is at step 2). */
    get canApplyLot() {
        return (
            !!this.state.production_id &&
            this.state.finished_product_tracking !== "none" &&
            (!!this.state.finished_lot_id || !!this.state.finished_lot_name) &&
            (this.state.finished_qty_producing || 0) > 0
        );
    }

    /** Confirm visible: a component is scanned (product + qty + lot if tracked).
     *  Mirrors the old form invisible condition. */
    get canConfirm() {
        return (
            !!this.state.production_id &&
            !!this.state.product_id &&
            (this.state.product_qty || 0) > 0 &&
            (this.state.product_tracking === "none" ||
                !!this.state.lot_id ||
                !!this.state.lot_name_raw)
        );
    }

    /** Finish Production visible: MO is in a finish-able state. */
    get canFinish() {
        return (
            !!this.state.production_id &&
            !["draft", "done", "cancel"].includes(this.state.production_state)
        );
    }

    /**
     * Unified RPC handler for wizard action methods.
     * - If the backend returns an action dict (act_window, e.g. consumption
     *   warning / backorder from button_mark_done), doAction it.
     * - Otherwise (True / False / move_lines dict), just refresh state.
     */
    async _callAction(methodName, errorLabel) {
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.mrp",
                methodName,
                [[this.wizId]]
            );
            if (res && typeof res === "object" && res.type) {
                this.actionService.doAction(res);
            } else {
                await this._refreshState();
            }
        } catch (err) {
            this.notification.add(
                _t("%(label)s failed: %(err)s", {
                    label: errorLabel || methodName,
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
        }
    }

    /** Confirm consumed component. */
    onConfirm() {
        return this._callAction("action_confirm", _t("Confirm"));
    }

    /** Force-consume a component (allow over-reserved consumption). */
    onForceDone() {
        return this._callAction("action_force_done", _t("Force Consume"));
    }

    /** Apply the scanned finished lot to the MO (bind SN, keep scanning). */
    onApplyLot() {
        return this._callAction("action_apply_finished_lot", _t("Apply Lot"));
    }

    /** Finish production: auto-applies pending lot, then marks MO done. */
    onFinishProduction() {
        return this._callAction("action_finish_production", _t("Finish Production"));
    }
}

registry
    .category("actions")
    .add("stock_barcodes_mrp_scan_app", MrpScanApp);
