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

    /** Confirm button — call the wizard's action_confirm method. */
    async onConfirm() {
        try {
            await this.orm.call(
                "wiz.stock.barcodes.mrp",
                "action_confirm",
                [[this.wizId]]
            );
            await this._refreshState();
        } catch (err) {
            this.notification.add(
                _t("Confirm failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
        }
    }

    /** Force-done button — call the wizard's force_done method. */
    async onForceDone() {
        try {
            await this.orm.call(
                "wiz.stock.barcodes.mrp",
                "action_force_done",
                [[this.wizId]]
            );
            await this._refreshState();
        } catch (err) {
            this.notification.add(
                _t("Force-done failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
        }
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
}

registry
    .category("actions")
    .add("stock_barcodes_mrp_scan_app", MrpScanApp);
