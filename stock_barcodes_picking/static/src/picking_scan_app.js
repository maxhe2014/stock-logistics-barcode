// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { Component, useState, onWillStart, onPatched, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";
import { browser } from "@web/core/browser/browser";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { CogMenu } from "@web/search/cog_menu/cog_menu";

/**
 * ScanCogMenu — thin wrapper around Odoo's native CogMenu that skips the
 * cogMenuRegistry entries (archive / restore / sync calendar / ...).
 * Those registry items run ``isDisplayed(env)`` callbacks that touch
 * ``env.searchModel``, which our client action does not have because we
 * are a client action, not a search-based view. Without the registry
 * items the component behaves identically to what the picking form view
 * shows — a single gear button holding the picking form's toolbar actions
 * (Unreserve / Scrap / Lock / Split / Create Repair) and print reports.
 */
export class ScanCogMenu extends CogMenu {
    async _registryItems() {
        return [];
    }
}

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
    static components = { AutoComplete, CogMenu: ScanCogMenu };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.barcodeService = useService("barcode");
        this.dialogService = useService("dialog");
        this._closePackageDialog = null;
        // Global keyboard scanner: any barcode_scanned event from the CE
        // barcode service triggers _onScan. Covers hardware scanners and
        // the mobile camera scanner alike.
        useBus(this.barcodeService.bus, "barcode_scanned", (ev) =>
            this._onScan(ev.detail.barcode)
        );

        this.wizId = this.props.action.params?.wiz_id;

        // Browser back button handling — preserve the source list's context.
        //
        // When this scan app mounts, the controller's onMounted hook overwrites
        // sessionStorage["current_action"] with the scan action.  We capture
        // the *previous* action (the picking list, with its full menu-applied
        // context such as the "incoming receipts" filter) *before* that
        // happens, so it is still available here in setup().
        //
        // On browser back, Odoo's normal popstate → loadState path reloads
        // the list action by its numeric ID, which drops the menu context and
        // shows *all* operations instead of just receipts.  To prevent that,
        // we restore the captured previous action into sessionStorage before
        // Odoo's popstate handler reads it.  actionService._getActionParams
        // then matches lastAction.id against state.action and reuses the full
        // action (with context) instead of loading a bare copy by ID.
        //
        // Unlike the previous historyBack() approach, this does NOT call
        // restore()/_updateUI/pushState, so no extra browser-history entries
        // are created and the controller stack stays in sync with history —
        // avoiding the freeze that occurred after repeated enter/back cycles.
        try {
            this._previousAction = browser.sessionStorage.getItem("current_action");
        } catch {
            this._previousAction = null;
        }
        this._onPopState = () => {
            if (this._previousAction) {
                browser.sessionStorage.setItem("current_action", this._previousAction);
            }
        };
        // Local UI mirror of the wizard state. Hydrated from
        // ``get_scan_state()`` after every interaction; rendered by the
        // t-* directives in the template.
        // Scans arriving while an RPC is in flight are buffered here and
        // drained in order (see _onScan), so fast scanners lose nothing.
        this._scanQueue = [];
        this._pendingScanTarget = null;
        this.state = useState({
            message: "",
            message_type: "info",
            moreMenuOpen: false,
            expandedRowKey: false,
            splitDialogOpen: false,
            splitPackages: [],
            // Unclaim-by-scan package chooser (quantity-tracked product
            // picked in several packages).
            unclaim_product_id: false,
            unclaim_product_name: "",
            unclaim_choices: [],
            editLine: false,
            picking_id: false,
            picking_name: "",
            picking_state: "",
            picking_type_code: "",
            barcode_lot_scan_policy: "mandatory",
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
            // Row-level selection. A move can render several rows (package
            // split / unpacked remainder), so highlighting must follow the
            // clicked row instead of every row sharing active_move_id.
            active_row_key: "",
            active_move_product_name: "",
            scan_steps: [],
            step: 0,
            move_ids: [],
            scanning: false,
            // Local UI state (not from backend)
            last_unmatched_barcode: "",
            editingQtyMoveId: false,
            draftQty: "",
            // Exact lot/move-line inline correction state.
            editingLotKey: "",
            editingLotLineId: false,
            draftLotQty: "",
            editingReservedLotKey: "",
            draftReservedLotQty: "",
            // Composite row_key:lot_id kept highlighted until the next scan.
            recentScanLotKey: "",
            // 每行最后一次扫码的批次 id（收起时头部优先显示它）
            lastScannedLotByRow: {},
            // Package rename inline editor (AutoComplete with existing names)
            editingPackageMoveId: false,
            editingPackageId: false,
            packageDraftName: "",
            // Serial cards expanded state, keyed by row_key. Local UI only.
            // Empty map = every serial card starts collapsed.
            expandedSerialRows: {},
            // Pull-to-refresh feedback: "idle" | "pulling" | "ready" |
            // "refreshing" (also used by the topbar refresh button).
            pullRefresh: "idle",
        });

        // Pull-to-refresh gesture state (touch + mouse drag).
        this._ptrActive = false;
        this._ptrStartY = 0;
        this._ptrStartX = 0;
        this._ptrDistance = 0;
        this._onPtrTouchStart = (ev) => this.onPtrTouchStart(ev);
        this._onPtrTouchMove = (ev) => this.onPtrTouchMove(ev);
        this._onPtrTouchEnd = () => this.onPtrTouchFinish();
        this._onPtrMouseDown = (ev) => this.onPtrMouseDown(ev);
        this._onPtrMouseMove = (ev) => this.onPtrMouseMove(ev);
        this._onPtrMouseUp = () => this.onPtrTouchFinish();

        // Sound alert for scan errors. Only an error tone is used
        // (success is silent). Preloaded so the first error plays
        // without a network round-trip.
        this.soundKo = new Audio(
            "/stock_barcodes_picking/static/src/sounds/error.wav"
        );

        onWillStart(async () => {
            if (!this.wizId) {
                // Direct visits to the scan action (old bookmarks, action 690
                // without params) go to the scan workbench instead of showing
                // an empty scan shell.
                await this.actionService.doAction(
                    "stock_barcodes_picking.action_scan_workbench"
                );
                return;
            }
            await this._refreshState();
        });

        // After a successful serial scan, keep the scanned lot visible without
        // moving the viewport when it is already on screen. Only the move-list
        // container is adjusted, never the outer Odoo page.
        onPatched(() => {
            const target = this._pendingScanTarget;
            if (!target) {
                return;
            }
            this._pendingScanTarget = null;
            const container = document.querySelector(".o_picking_scan_moves");
            if (!container) {
                return;
            }
            // v4 rows are keyed by move id; the wizard's move row_key is a
            // composite (id_package_location), so translate before lookup.
            const rowKey = target.moveId ? String(target.moveId) : target.rowKey;
            const lotKey = `${rowKey}:${target.lotId}`;
            const el = container.querySelector(`[data-scan-lot="${lotKey}"]`)
                || container.querySelector(`[data-scan-row="${rowKey}"]`);
            if (!el) {
                return;
            }
            const margin = 8;
            const containerRect = container.getBoundingClientRect();
            const targetRect = el.getBoundingClientRect();
            if (targetRect.top < containerRect.top + margin) {
                container.scrollTop -= containerRect.top + margin - targetRect.top;
            } else if (targetRect.bottom > containerRect.bottom - margin) {
                container.scrollTop += targetRect.bottom - containerRect.bottom + margin;
            }
        });

        // Register the popstate listener in the capture phase so it runs
        // before Odoo's own router listener, ensuring current_action is
        // restored before loadState → _getActionParams reads it.
        onMounted(() => {
            window.addEventListener("popstate", this._onPopState, { capture: true });
            // Pull-to-refresh is bound on the component root (the gesture
            // may start on the list, the hint bar or any empty area) and
            // directly in JS so touchmove is explicitly non-passive and
            // can stop the browser's native overscroll while pulling.
            const root = this.el;
            if (root) {
                root.addEventListener("touchstart", this._onPtrTouchStart, {
                    passive: true,
                });
                root.addEventListener("touchmove", this._onPtrTouchMove, {
                    passive: false,
                });
                root.addEventListener("touchend", this._onPtrTouchEnd);
                root.addEventListener("touchcancel", this._onPtrTouchEnd);
                root.addEventListener("mousedown", this._onPtrMouseDown);
                // Mouse dragging (desktop / testing) continues outside the
                // action root, so move/up are tracked on the window.
                window.addEventListener("mousemove", this._onPtrMouseMove);
                window.addEventListener("mouseup", this._onPtrMouseUp);
            }
        });
        onWillUnmount(() => {
            window.removeEventListener("popstate", this._onPopState, { capture: true });
            const root = this.el;
            if (root) {
                root.removeEventListener("touchstart", this._onPtrTouchStart);
                root.removeEventListener("touchmove", this._onPtrTouchMove);
                root.removeEventListener("touchend", this._onPtrTouchEnd);
                root.removeEventListener("touchcancel", this._onPtrTouchEnd);
                root.removeEventListener("mousedown", this._onPtrMouseDown);
            }
            window.removeEventListener("mousemove", this._onPtrMouseMove);
            window.removeEventListener("mouseup", this._onPtrMouseUp);
            this._closePackageDialog?.();
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
        this._syncActiveRow();
    }

    /**
     * Keep the selected row consistent with the backend active move, while
     * never highlighting more than one row. Several rows can share one
     * move_id (one row per destination package), so the visual selection is
     * tracked with row_key.
     */
    _syncActiveRow() {
        const rows = this.state.rows || [];
        const activeMove = this.state.active_move_id;
        const current = rows.find(
            (row) => row.row_key === this.state.active_row_key
        );
        if (current && current.move_id === activeMove) {
            return;
        }
        const fallback = activeMove
            ? rows.find((row) => row.move_id === activeMove)
            : null;
        this.state.active_row_key = fallback ? fallback.row_key : "";
    }

    // ---------- pull-to-refresh + topbar refresh button ----------

    /**
     * Topbar refresh button: re-read the transfer from the server (moves,
     * packages, demand) without leaving the scan screen or losing the
     * current selection.
     */
    async onRefreshPicking() {
        if (this.state.scanning) {
            return;
        }
        await this._runRefresh();
    }

    /** The scrollable product list (used for the "at top" check). */
    _ptrScrollContainer() {
        return this.el?.querySelector(".o_picking_scan_rows") || null;
    }

    /**
     * Can a pull gesture start from this touch/drag?
     *
     * The list must be at its top, no scan/edit/dialog may run, and the
     * gesture must not start on an interactive control (so tapping a
     * button, input or link keeps its normal behaviour).
     */
    _ptrCanStart(target) {
        const rows = this._ptrScrollContainer();
        if (!rows || rows.scrollTop > 0) {
            return false;
        }
        if (
            this.state.scanning
            || this.state.editLine
            || this.state.splitDialogOpen
            || this.state.visible_switch_selector
            || this.state.unclaim_choices.length
        ) {
            return false;
        }
        return !target?.closest?.("button, a, input, textarea, select, .btn");
    }

    _ptrBegin(clientY, clientX) {
        this._ptrActive = true;
        this._ptrStartY = clientY;
        this._ptrStartX = clientX;
        this._ptrDistance = 0;
    }

    /**
     * Track the drag. Returns true when the browser's native gesture
     * (overscroll, text selection) must be blocked.
     */
    _ptrUpdate(clientY, clientX) {
        if (!this._ptrActive) {
            return false;
        }
        const dy = clientY - this._ptrStartY;
        const dx = Math.abs(clientX - this._ptrStartX);
        if (dy <= 0 || dx > Math.max(30, dy)) {
            this._ptrActive = false;
            this.state.pullRefresh = "idle";
            return false;
        }
        // Rubber-band factor: the indicator tracks the drag but never
        // reaches the full distance.
        this._ptrDistance = Math.min(90, dy * 0.5);
        this.state.pullRefresh = this._ptrDistance >= 55 ? "ready" : "pulling";
        // Block native scrolling/selection as soon as the pull starts;
        // waiting longer lets mobile browsers lock into a native gesture.
        return this._ptrDistance > 2;
    }

    onPtrTouchStart(ev) {
        if (ev.touches.length !== 1 || !this._ptrCanStart(ev.target)) {
            this._ptrActive = false;
            return;
        }
        this._ptrBegin(ev.touches[0].clientY, ev.touches[0].clientX);
    }

    onPtrTouchMove(ev) {
        if (!this._ptrActive || ev.touches.length !== 1) {
            return;
        }
        if (this._ptrUpdate(ev.touches[0].clientY, ev.touches[0].clientX)) {
            ev.preventDefault();
        }
    }

    onPtrMouseDown(ev) {
        if (ev.button !== 0 || !this._ptrCanStart(ev.target)) {
            this._ptrActive = false;
            return;
        }
        this._ptrBegin(ev.clientY, ev.clientX);
    }

    onPtrMouseMove(ev) {
        if (this._ptrUpdate(ev.clientY, ev.clientX)) {
            ev.preventDefault();
        }
    }

    /** Release: refresh when the pull passed the threshold. */
    async onPtrTouchFinish() {
        if (!this._ptrActive) {
            return;
        }
        const trigger = this._ptrDistance >= 55;
        this._ptrActive = false;
        this._ptrDistance = 0;
        if (!trigger) {
            this.state.pullRefresh = "idle";
            return;
        }
        await this._runRefresh();
    }

    /** Shared refresh with the "刷新中…" indicator. */
    async _runRefresh() {
        this.state.pullRefresh = "refreshing";
        try {
            await this._refreshState();
        } finally {
            this.state.pullRefresh = "idle";
        }
    }

    /**
     * Add a `pickedLots` filtered array to each move so a newly picked lot
     * can be located after the backend refresh.
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
     * Scan entry point — serializes scans through a queue.
     *
     * A hardware scanner can fire faster than the per-scan RPC round trip;
     * previously those scans were silently dropped. Every barcode is now
     * queued and processed in order by a single worker, so a burst of
     * scans cannot lose codes (each scan is still one RPC).
     */
    async _onScan(barcode) {
        if (!barcode) {
            return;
        }
        if (this.isQuantityEditing) {
            this.notification.add(
                _t("Finish or cancel quantity editing before scanning."),
                { type: "warning" }
            );
            return;
        }
        this._scanQueue.push(barcode);
        if (this.state.scanning) {
            // A running worker will drain the queue.
            return;
        }
        while (this._scanQueue.length) {
            await this._scanOne(this._scanQueue.shift());
        }
    }

    /**
     * Core scan handler — single RPC entry.
     * Calls process_barcode_and_dispatch(barcode) → {action, state}.
     * Tracks the last unmatched barcode so the "Force add?" button can
     * pass it back to action_force_add_from_barcode.
     */
    async _scanOne(barcode) {
        // When the candidate selector is open, the manual input is
        // disabled, but the hardware scanner can still fire. Let the
        // scan through — the backend guard only accepts picking-name
        // scans while the selector is open, and rejects everything else.
        this.state.scanning = true;
        // Snapshot picked quantities per package row and lot. Comparing only
        // lot IDs misses repeated scans of an existing lot (the common case
        // when a lot is already packed or unpacked).
        const pickedLotQuantitiesBefore = new Map();
        for (const mv of this.state.move_ids) {
            for (const lot of mv.pickedLots || []) {
                pickedLotQuantitiesBefore.set(
                    `${mv.row_key}:${lot.id}`,
                    lot.picked_quantity || 0
                );
            }
        }
        // 任何一次新扫描都先清掉上一行的高亮；只有命中序列号/批号时才重新点亮。
        this.state.recentScanLotKey = "";
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
            // Locate the lot whose picked quantity increased. The row key is
            // part of the identity so equal lot IDs in different packages
            // cannot steal the highlight from the actual scanned row.
            let scannedTarget = null;
            for (const mv of this.state.move_ids) {
                const scannedLot = (mv.pickedLots || []).find((lot) => {
                    const beforeQty = pickedLotQuantitiesBefore.get(
                        `${mv.row_key}:${lot.id}`
                    ) || 0;
                    return (lot.picked_quantity || 0) > beforeQty;
                });
                if (!scannedLot) {
                    continue;
                }
                mv.pickedLots = mv.pickedLots.filter((lot) => lot.id !== scannedLot.id);
                mv.pickedLots.push(scannedLot);
                mv.latest_lot_id = scannedLot.id;
                scannedTarget = {
                    rowKey: mv.row_key,
                    moveId: mv.id,
                    lotId: scannedLot.id,
                };
                break;
            }
            if (scannedTarget) {
                this._pendingScanTarget = scannedTarget;
                // 高亮一直保留，直到下一次扫描把它清掉 / 换成新的行。
                // v4 模板以 move id 作为行键（state.rows[].row_key）。
                this.state.recentScanLotKey = `${scannedTarget.moveId}:${scannedTarget.lotId}`;
                this.state.lastScannedLotByRow = {
                    ...this.state.lastScannedLotByRow,
                    [String(scannedTarget.moveId)]: scannedTarget.lotId,
                };
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

    /** Open the device camera and feed the detected code into the normal scan queue. */
    async onCameraScan() {
        if (
            this.state.scanning ||
            this.isQuantityEditing ||
            this.state.visible_switch_selector ||
            this.state.visible_force_add
        ) {
            return;
        }
        try {
            const barcode = await scanBarcode(this.env, "environment");
            if (barcode?.trim()) {
                await this._onScan(barcode.trim());
            }
        } catch (err) {
            this.notification.add(
                _t("Scan failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
            this._playAlert();
        }
    }

    /** Back button — return to the previous controller (the picking list). */
    onBack() {
        this.env.config.historyBack();
    }

    /** Open the source/origin document (sale.order / purchase.order / ...).
     *  Falls back to the picking form when no origin is resolvable. */
    onOpenSourcePicking() {
        const { origin_model, origin_id } = this.state;
        if (origin_model && origin_id) {
            this.actionService.doAction({
                res_model: origin_model,
                res_id: origin_id,
                views: [[false, "form"]],
                type: "ir.actions.act_window",
                target: "current",
            });
            return;
        }
        // No origin available — fall back to the picking itself so the
        // button at least always does something useful.
        if (this.state.picking_id) {
            this.actionService.doAction({
                res_model: "stock.picking",
                res_id: this.state.picking_id,
                views: [[false, "form"]],
                type: "ir.actions.act_window",
                target: "current",
            });
        }
    }

    /** Open this transfer's picking form (top-bar document name link). */
    onOpenPicking() {
        if (!this.state.picking_id) {
            return;
        }
        this.actionService.doAction({
            res_model: "stock.picking",
            res_id: this.state.picking_id,
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            target: "current",
        });
    }

    /** Jump to the source transfer form so the operator can use the
     *  native Odoo action menu (gear icon) — print, ZPL labels, scrap,
     *  cancel, etc. — all of which live on the form/header controller
     *  and can't be triggered cleanly from this client action. */
    onOpenPickingActions() {
        if (!this.state.picking_id) {
            return;
        }
        this.actionService.doAction({
            res_model: "stock.picking",
            res_id: this.state.picking_id,
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            target: "current",
        });
    }

    /** Open product picker → add the selected product to the current
     *  picking (backend creates a new stock.move) → refresh state so the
     *  new card appears on the scan view. */
    onAddProduct() {
        this.state.moreMenuOpen = false;
        this.dialogService.add(
            SelectCreateDialog,
            {
                resModel: "product.product",
                title: _t("选择或创建产品"),
                noCreate: false,
                onSelected: async (resIds) => {
                    // SelectCreateDialog 传 resIds（纯数字 ID 数组），
                    // 不是 record 对象数组！records?.[0]?.id 会得到 undefined。
                    const productId = resIds?.[0];
                    if (!productId) {
                        this.notification.add(
                            _t("请先选择一个产品"),
                            { type: "warning" }
                        );
                        return;
                    }
                    try {
                        this.notification.add(
                            _t("正在添加产品 (id=%(id)s)...", { id: productId }),
                            { type: "info" }
                        );
                        const result = await this.orm.call(
                            "wiz.stock.barcodes.picking",
                            "action_add_product_to_picking",
                            [this.wizId],
                            { product_id: productId }
                        );
                        this.notification.add(
                            _t("后端返回: %(res)s", { res: String(result) }),
                            { type: result ? "success" : "warning" }
                        );
                        await this._refreshState();
                        this.notification.add(
                            _t("已刷新产品列表"),
                            { type: "success" }
                        );
                    } catch (err) {
                        this.notification.add(
                            _t("添加产品失败: %(err)s", {
                                err: err?.message || JSON.stringify(err),
                            }),
                            { type: "danger" }
                        );
                        console.error("onAddProduct error:", err);
                    }
                },
            },
            { onClose: () => {} }
        );
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

    /** Confirm or discard an outside product identified by its serial. */
    onConfirmNewProduct() {
        return this._callAction(
            "action_confirm_new_product",
            _t("Add Product and Pick")
        );
    }

    onCancelNewProduct() {
        return this._callAction("action_cancel_new_product", _t("Cancel"));
    }

    /**
     * Click a move row to preselect the target move.
     * Narrow subsequent lot/qty scans to this move.
     */
    async onSelectMove(moveId, rowKey) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        // Toggle on the clicked row (not on the move): a move can be split
        // into several rows, and clicking one must not select the others.
        const isSameRow = this.state.active_row_key === rowKey;
        const targetId = isSameRow ? false : moveId;
        try {
            const ok = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "set_active_move",
                [[this.wizId], targetId]
            );
            if (ok) {
                this.state.active_row_key = targetId ? rowKey : "";
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

    get isQuantityEditing() {
        return Boolean(
            this.state.editingQtyMoveId
            || this.state.editingLotKey
            || this.state.editingReservedLotKey
        );
    }

    /** Enter inline quantity-edit mode for a move row (pencil button).
     *  Pre-fills the draft with the move demand. */
    onEditMoveQty(rowKey) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        const mv = this.state.move_ids.find((m) => m.row_key === rowKey);
        if (!mv) {
            return;
        }
        this.onCancelLotQty();
        this.onCancelReservedLotQty();
        this.state.editingQtyMoveId = rowKey;
        // Pre-fill with the demand shown on this row (a package row shows
        // what it holds, the unpacked row shows what is not packaged yet).
        this.state.draftQty = String(mv.demand_qty ?? mv.product_uom_qty ?? 0);
    }

    onDraftQtyInput(ev) {
        this.state.draftQty = ev.currentTarget.value;
    }

    onDraftQtyKeydown(ev, rowKey) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmMoveQty(rowKey);
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
    async onConfirmMoveQty(rowKey) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        const mv = this.state.move_ids.find((m) => m.row_key === rowKey);
        if (!mv) {
            return;
        }
        const qty = parseFloat(this.state.draftQty);
        if (Number.isNaN(qty) || qty < 0) {
            this.notification.add(_t("Please enter a quantity"), {
                type: "danger",
            });
            this._playAlert();
            return;
        }
        this.state.scanning = true;
        try {
            if (qty === 0) {
                // 输入 0 = 清空该行（设计稿去掉删除按钮，只保留修改按钮）
                const res = mv.package_id
                    ? await this.orm.call(
                        "wiz.stock.barcodes.picking",
                        "action_edit_package_qty",
                        [[this.wizId], mv.id, mv.package_id, 0]
                    )
                    : await this.orm.call(
                        "wiz.stock.barcodes.picking",
                        "action_remove_move_qty",
                        [[this.wizId], rowKey]
                    );
                await this._handleActionResult(res, "Clear quantity");
            } else if (mv.package_id) {
                // Packaged row: the consume flow below only SETs unpacked
                // lines, so edit the lines that actually sit in this package.
                let res = await this.orm.call(
                    "wiz.stock.barcodes.picking",
                    "action_edit_package_qty",
                    [[this.wizId], mv.id, mv.package_id, qty]
                );
                if (res === false) {
                    await this._refreshState();
                    if (this.state.message_type !== "more_match") {
                        this._playAlert();
                        return;
                    }
                    const force = window.confirm(
                        `${this.state.message}\n${_t("Continue?")}`
                    );
                    if (!force) {
                        return;
                    }
                    res = await this.orm.call(
                        "wiz.stock.barcodes.picking",
                        "action_edit_package_qty",
                        [[this.wizId], mv.id, mv.package_id, qty, true]
                    );
                }
                this.state.active_row_key = mv.row_key;
                await this._handleActionResult(res, "Edit quantity");
            } else {
                // 1. Bind the target move
                const ok = await this.orm.call(
                    "wiz.stock.barcodes.picking",
                    "set_active_move",
                    [[this.wizId], mv.id]
                );
                if (!ok) {
                    await this._refreshState();
                    this._playAlert();
                    return;
                }
                this.state.active_row_key = mv.row_key;
                // 2. Consume with the entered quantity
                const res = await this.orm.call(
                    "wiz.stock.barcodes.picking",
                    "action_consume_with_qty",
                    [[this.wizId], qty]
                );
                await this._handleActionResult(res, "Consume");
            }
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
     * ``+1`` button of a quantity row: add one unit to that row's picked
     * total. ``packageId`` scopes it to the clicked row (a destination
     * package, or the unpacked remainder) because a move with packed
     * lines is split into several product rows like the official app.
     */
    async onAddMoveQuantity(moveId, quantity = null, packageId = null) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_add_move_quantity",
                [[this.wizId], moveId, quantity, packageId]
            );
            await this._handleActionResult(res, "Add quantity");
        } catch (err) {
            this.notification.add(
                _t("Add quantity failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    async _pickReservedLot(moveId, lotId, quantity) {
        if (this.state.scanning || !this.wizId) {
            return false;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_pick_reserved_lot",
                [[this.wizId], moveId, lotId, quantity]
            );
            await this._handleActionResult(res, "Pick reserved lot");
            return res !== false;
        } catch (err) {
            this.notification.add(
                _t("Pick reserved lot failed: %(err)s", { err: err?.message || String(err) }),
                { type: "danger" }
            );
            this._playAlert();
            return false;
        } finally {
            this.state.scanning = false;
        }
    }

    onPickReservedLot(moveId, lotId) {
        return this._pickReservedLot(moveId, lotId, 1);
    }

    onEditReservedLotQty(rowKey, lotKey) {
        const lot = this._findLot(rowKey, lotKey);
        if (!lot || lot.picked) {
            return;
        }
        this.onCancelMoveQty();
        this.onCancelLotQty();
        this.state.editingReservedLotKey = `${rowKey}:${lotKey}`;
        this.state.draftReservedLotQty = String(lot.reserved_quantity || 0);
    }

    onDraftReservedLotQtyInput(ev) {
        this.state.draftReservedLotQty = ev.currentTarget.value;
    }

    onCancelReservedLotQty() {
        this.state.editingReservedLotKey = "";
        this.state.draftReservedLotQty = "";
    }

    onDraftReservedLotQtyKeydown(ev, rowKey, lotId) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmReservedLotQty(rowKey, lotId);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.onCancelReservedLotQty();
        }
    }

    async onConfirmReservedLotQty(rowKey, lotId) {
        const qty = parseFloat(this.state.draftReservedLotQty);
        if (!qty || qty <= 0) {
            this.notification.add(_t("Please enter a positive quantity"), {
                type: "danger",
            });
            this._playAlert();
            return;
        }
        const mv = this.state.move_ids.find((move) => move.row_key === rowKey);
        if (!mv) {
            return;
        }
        const done = await this._pickReservedLot(mv.id, lotId, qty);
        if (done) {
            this.onCancelReservedLotQty();
        }
    }

    _findLot(rowKey, lotKey) {
        const mv = this.state.move_ids.find((m) => m.row_key === rowKey);
        return mv?.lots.find((lot) => lot.key === lotKey);
    }

    /** Open the exact-line editor for one picked lot badge. */
    onEditLotQty(rowKey, lotKey) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        const lot = this._findLot(rowKey, lotKey);
        if (!lot?.picked || !lot.lines?.length) {
            return;
        }
        this.onCancelMoveQty();
        this.onCancelReservedLotQty();
        this.state.editingLotKey = `${rowKey}:${lotKey}`;
        this.state.editingLotLineId = false;
        this.state.draftLotQty = "";
        if (lot.lines.length === 1) {
            this.onSelectLotLine(lot.lines[0]);
        }
    }

    onSelectLotLine(line) {
        this.state.editingLotLineId = line.id;
        this.state.draftLotQty = String(line.quantity || 0);
    }

    onDraftLotQtyInput(ev) {
        this.state.draftLotQty = ev.currentTarget.value;
    }

    onDraftLotQtyKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onConfirmLotQty();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.onCancelLotQty();
        }
    }

    onCancelLotQty() {
        this.state.editingLotKey = "";
        this.state.editingLotLineId = false;
        this.state.draftLotQty = "";
    }

    /** Save one exact line; a warn policy requires a second confirmation. */
    async onConfirmLotQty() {
        if (this.state.scanning || !this.wizId || !this.state.editingLotLineId) {
            return;
        }
        const lineId = this.state.editingLotLineId;
        const qty = parseFloat(this.state.draftLotQty);
        if (Number.isNaN(qty) || qty < 0) {
            this.notification.add(_t("Please enter a quantity"), {
                type: "danger",
            });
            this._playAlert();
            return;
        }
        if (qty === 0) {
            // 输入 0 = 移除该批次/序列号行（替代已去掉的删除按钮）
            this.onCancelLotQty();
            await this._removeMoveLine(lineId);
            return;
        }
        this.state.scanning = true;
        try {
            let res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_edit_move_line_qty",
                [[this.wizId], lineId, qty]
            );
            if (res === false) {
                await this._refreshState();
                if (this.state.message_type !== "more_match") {
                    this._playAlert();
                    return;
                }
                const force = window.confirm(
                    `${this.state.message}\n${_t("Continue?")}`
                );
                if (!force) {
                    return;
                }
                res = await this.orm.call(
                    "wiz.stock.barcodes.picking",
                    "action_edit_move_line_qty",
                    [[this.wizId], lineId, qty, true]
                );
            }
            await this._handleActionResult(res, "Edit lot quantity");
            if (res) {
                this.onCancelLotQty();
            }
        } catch (err) {
            this.notification.add(
                _t("Edit lot quantity failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    async _removeMoveLine(lineId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_remove_move_lot",
                [[this.wizId], lineId]
            );
            await this._handleActionResult(res, "Remove lot");
            if (res) {
                this.onCancelLotQty();
            }
        } catch (err) {
            this.notification.add(
                _t("Remove lot failed: %(err)s", {
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
     * Clear the whole picked quantity of one row (quantity-tracked
     * products). Reached by entering 0 in the row's edit field — the
     * design has no dedicated delete button any more.
     */
    async onRemoveMoveQty(rowKey) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_remove_move_qty",
                [[this.wizId], rowKey]
            );
            await this._handleActionResult(res, "Remove quantity");
            if (res) {
                this.onCancelMoveQty();
            }
        } catch (err) {
            this.notification.add(
                _t("Remove quantity failed: %(err)s", {
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
     * Toggle the one-shot pack intent: the next package scan binds the
     * unpacked picked lines instead of picking the package as a whole.
     */
    onSetPackIntent() {
        return this._callAction(
            "action_set_pack_intent",
            _t("Pack intent")
        );
    }

    /**
     * Confirm picking a serial whose reservation lives in another transfer.
     */
    onConfirmCrossOrder() {
        return this._callAction(
            "action_confirm_cross_order_pick",
            _t("Confirm cross-order pick")
        );
    }

    /** Open the row editor for one lot line (quantity/lot/packages).
     *
     * Quantity-tracked rows aggregate every picked line of the product,
     * so their editor works on the row total (`qtyOnly`) and has no lot
     * field. Packages are still editable: a single shared name is
     * pre-filled, and saving applies it to every picked line of the row.
     */
    onOpenLineEditor(lot, row = null) {
        const lineId = (lot.line_ids || [])[0] || false;
        if (!lineId) {
            return;
        }
        const qtyOnly = Boolean(row && row.tracking === "none");
        let packageFrom = lot.package_from || "";
        let packageTo = lot.package_to || "";
        if (qtyOnly) {
            // The row may span several packages: only pre-fill the name
            // when it is unambiguous, otherwise leave it blank (= keep).
            const lots = row.lots || [];
            const from = [...new Set(lots.map((l) => l.package_from).filter(Boolean))];
            const to = [...new Set(lots.map((l) => l.package_to).filter(Boolean))];
            packageFrom = from.length === 1 ? from[0] : "";
            packageTo = to.length === 1 ? to[0] : "";
        }
        this.state.editLine = {
            lineId: lineId,
            qty: qtyOnly ? row.picked_qty || 0 : lot.quantity || 0,
            lotName: qtyOnly ? "" : lot.name || "",
            packageFrom: packageFrom,
            packageTo: packageTo,
            serial: false,
            qtyOnly: qtyOnly,
        };
    }

    onCloseLineEditor() {
        this.state.editLine = false;
    }

    /** Save the row editor through action_edit_move_line. */
    async onSaveLineEditor() {
        const edit = this.state.editLine;
        if (!edit || !edit.lineId || this.state.scanning || !this.wizId) {
            return;
        }
        const qty = Number.isNaN(parseFloat(edit.qty))
            ? null
            : parseFloat(edit.qty);
        const qtyOnly = Boolean(edit.qtyOnly);
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_edit_move_line",
                [
                    [this.wizId],
                    edit.lineId,
                    qty,
                    // null (not false) leaves the field untouched; false
                    // would clear the lot/package of the line.
                    qtyOnly ? null : edit.lotName || false,
                    // Aggregated rows keep their packages when the field
                    // is left blank, so one empty field cannot wipe the
                    // packages of every line of the row.
                    edit.packageFrom || (qtyOnly ? null : false),
                    edit.packageTo || (qtyOnly ? null : false),
                ]
            );
            this.state.editLine = false;
            await this._handleActionResult(res, _t("Edit line"));
        } catch (err) {
            this.notification.add(
                _t("Edit line failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Collapse/expand the lot list of a product row. */
    onToggleRowLots(rowKey) {
        this.state.expandedRowKey =
            this.state.expandedRowKey === rowKey ? false : rowKey;
    }

    /** Is the lot dropdown of this row expanded? */
    isRowExpanded(row) {
        return this.state.expandedRowKey === row.row_key;
    }

    /**
     * Lot shown in the collapsed header: the last lot scanned for this row,
     * falling back to the last scanned lot globally, then a picked lot, then
     * the first one.
     */
    headerLot(row) {
        const lots = row.lots || [];
        if (!lots.length) {
            return false;
        }
        const lastId = this.state.lastScannedLotByRow[row.row_key];
        if (lastId) {
            const hit = lots.find((lot) => lot.id === lastId);
            if (hit) {
                return hit;
            }
        }
        const recentKey = this.state.recentScanLotKey;
        if (recentKey && recentKey.startsWith(`${row.row_key}:`)) {
            const lotId = Number(recentKey.slice(row.row_key.length + 1));
            const hit = lots.find((lot) => lot.id === lotId);
            if (hit) {
                return hit;
            }
        }
        return lots.find((lot) => lot.picked) || lots[0];
    }

    /**
     * Quantity-tracked rows have no lot dropdown: expose the first picked
     * line (for the pencil) and the package chip shown under the card.
     */
    quantityEditLot(row) {
        const lots = row.lots || [];
        return (
            lots.find((lot) => lot.picked && lot.line_ids && lot.line_ids.length)
            || lots.find((lot) => lot.line_ids && lot.line_ids.length)
            || false
        );
    }

    quantityPackages(row) {
        const lots = row.lots || [];
        const from = [...new Set(lots.map((lot) => lot.package_from).filter(Boolean))];
        const to = [...new Set(lots.map((lot) => lot.package_to).filter(Boolean))];
        if (from.length === 1 && to.length === 1 && from[0] !== to[0]) {
            return `${from[0]} > ${to[0]}`;
        }
        const names = to.length ? to : from;
        return names.join(" , ");
    }

    /** Has this row reached its demand? (tints the picked qty)
     *
     * Split rows carry their own share of the demand (a package row
     * asks for what it holds, the remainder row for what is missing),
     * so a row is complete on its own numbers.
     */
    isRowComplete(row) {
        const picked = row.picked_qty || 0;
        const demand = row.demand_qty || 0;
        if (demand <= 0) {
            return picked > 0;
        }
        return picked + 1e-6 >= demand;
    }

    /** Edit the quantity of one picked lot line. */
    async onEditLotQtyV4(lineId, currentQty) {
        if (this.state.scanning || !this.wizId || !lineId) {
            return;
        }
        const value = window.prompt(_t("Quantity"), currentQty || 0);
        if (value === null) {
            return;
        }
        const qty = parseFloat(value);
        if (Number.isNaN(qty) || qty <= 0) {
            this.notification.add(_t("Please enter a quantity"), {
                type: "danger",
            });
            this._playAlert();
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_edit_move_line_qty",
                [[this.wizId], lineId, qty]
            );
            await this._handleActionResult(res, _t("Edit quantity"));
        } catch (err) {
            this.notification.add(
                _t("Edit quantity failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Translation helper for templates (QWeb has no global _t). */
    tr(text) {
        return _t(text);
    }

    /** Toggle the "more" action sheet (design: 更多…). */
    onToggleMoreMenu() {
        this.state.moreMenuOpen = !this.state.moreMenuOpen;
    }

    /** Close the more sheet when the user taps outside it. */
    onCloseMoreMenu() {
        this.state.moreMenuOpen = false;
    }

    /** Back to the direction default picking mode. */
    onExitScanMode() {
        this.state.moreMenuOpen = false;
        return this._callAction(
            "action_exit_scan_mode",
            _t("Return to picking mode")
        );
    }

    onStartSplitScan() {
        this.state.moreMenuOpen = false;
        return this._setScanMode("split_scan");
    }

    onStartUnclaimScan() {
        this.state.moreMenuOpen = false;
        return this._setScanMode("unclaim_scan");
    }

    /**
     * Package chooser of the unclaim / split flows: apply the operator's
     * choice (remove one unit from the chosen package).
     */
    async onSelectUnclaimPackage(packageId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const method = this.state.scan_mode === "split_scan"
                ? "action_split_unit"
                : "action_unclaim_unit";
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                method,
                [
                    [this.wizId],
                    this.state.unclaim_product_id,
                    packageId || false,
                ]
            );
            await this._handleActionResult(res, _t("Unclaim"));
        } catch (err) {
            this.notification.add(
                _t("Unclaim failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Close the unclaim package chooser without writing anything. */
    async onCancelUnclaim() {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_cancel_unclaim",
                [[this.wizId]]
            );
            await this._refreshState();
        } catch (err) {
            this.notification.add(
                _t("Unclaim failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Enter one of the non-default scan modes. */
    async _setScanMode(mode) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_set_scan_mode",
                [[this.wizId], mode]
            );
            await this._handleActionResult(res, _t("Scan mode"));
        } catch (err) {
            this.notification.add(
                _t("Scan mode failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    /** Split dialog: list the packages used by this transfer. */
    async onOpenSplitDialog() {
        this.state.moreMenuOpen = false;
        if (!this.wizId) {
            return;
        }
        try {
            this.state.splitPackages = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "get_picking_packages",
                [[this.wizId]]
            );
            this.state.splitDialogOpen = true;
        } catch (err) {
            this.notification.add(
                _t("Could not load packages: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
        }
    }

    onCloseSplitDialog() {
        this.state.splitDialogOpen = false;
        this.state.splitPackages = [];
    }

    /** Split dialog: drop the chosen package from every line. */
    async onConfirmRemovePackage(packageId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        if (!window.confirm(
            _t("Remove this package from every line of the transfer?")
        )) {
            return;
        }
        this.state.splitDialogOpen = false;
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_remove_package",
                [[this.wizId], packageId]
            );
            await this._handleActionResult(res, _t("Remove package"));
        } catch (err) {
            this.notification.add(
                _t("Remove package failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
            this.state.splitPackages = [];
        }
    }

    /**
     * Undo a whole-package scan: the package lines go back to not picked.
     */
    async onUndoPackageScan(packageId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        if (!window.confirm(
            _t("Undo this package scan? Its lines go back to not picked.")
        )) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_undo_package_scan",
                [[this.wizId], packageId]
            );
            await this._handleActionResult(res, "Undo package scan");
        } catch (err) {
            this.notification.add(
                _t("Undo failed: %(err)s", {
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
     * Open the inline package-rename editor (AutoComplete).
     *
     * Replaces the old window.prompt() with an Odoo-standard AutoComplete
     * that suggests existing package names via name_search while still
     * allowing the operator to type a brand-new name.
     */
    onEditPackageName(packageId, rowKey, currentName) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.editingPackageMoveId = rowKey;
        this.state.editingPackageId = packageId;
        this.state.packageDraftName = currentName || "";
    }

    /**
     * AutoComplete source: return existing package names matching the
     * typed text (name_search on stock.package).
     */
    async loadPackageNameOptions(name) {
        try {
            const results = await this.orm.call(
                "stock.package",
                "name_search",
                [],
                { name: name || "", limit: 8 }
            );
            const options = results.map(([id, label]) => ({
                label,
                onSelect: () => this._confirmPackageRename(label),
            }));
            if (options.length === 0) {
                options.push({ label: _t("(no existing package)") });
            }
            return options;
        } catch {
            return [];
        }
    }

    get packageNameSources() {
        return [
            {
                placeholder: _t("Loading..."),
                options: this.loadPackageNameOptions.bind(this),
            },
        ];
    }

    onPackageNameChange({ inputValue }) {
        this.state.packageDraftName = inputValue;
    }

    onPackageNameInput({ inputValue }) {
        this.state.packageDraftName = inputValue;
    }

    onPackageNameKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this._confirmPackageRename(this.state.packageDraftName);
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this._cancelPackageRename();
        }
    }

    async _confirmPackageRename(name) {
        const newName = (name || "").trim();
        if (!newName) {
            this.notification.add(_t("Package name cannot be empty."), {
                type: "danger",
            });
            return;
        }
        const packageId = this.state.editingPackageId;
        this._cancelPackageRename();
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_edit_package_name",
                [[this.wizId], packageId, newName]
            );
            await this._handleActionResult(res, "Rename package");
        } catch (err) {
            this.notification.add(
                _t("Rename failed: %(err)s", {
                    err: err?.message || String(err),
                }),
                { type: "danger" }
            );
            this._playAlert();
        } finally {
            this.state.scanning = false;
        }
    }

    _cancelPackageRename() {
        this.state.editingPackageMoveId = false;
        this.state.editingPackageId = false;
        this.state.packageDraftName = "";
    }

    /**
     * Unpack a package (clear result_package_id on its picked lines).
     *
     * @param {number} packageId - the package to remove
     * @param {number} [moveId] - scope the removal to lines of this move;
     *   prevents stripping a shared package from other products.
     */
    async onUnpackPackage(packageId, moveId) {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        if (!window.confirm(_t("Remove this package? Products will be unpacked."))) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_unpack_package",
                [[this.wizId], packageId, moveId || false]
            );
            await this._handleActionResult(res, "Unpack");
        } catch (err) {
            this.notification.add(
                _t("Unpack failed: %(err)s", {
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
     * Open a dialog to search and pick an existing package to bind
     * the unpacked picked lines to.
     */
    onSelectPackage() {
        if (this.state.scanning || !this.wizId || this._closePackageDialog) {
            return;
        }
        this.state.moreMenuOpen = false;
        this._closePackageDialog = this.dialogService.add(
            SelectCreateDialog,
            {
                resModel: "stock.package",
                title: _t("Select Package"),
                multiSelect: false,
                noCreate: true,
                onSelected: (resIds) => this.onPackageSelected({ id: resIds[0] }),
            },
            {
                onClose: () => {
                    this._closePackageDialog = null;
                },
            }
        );
    }

    /**
     * Package select callback: bind unpacked picked lines to the
     * selected package.
     */
    async onPackageSelected(value) {
        if (!value || !value.id) {
            return;
        }
        const packageId = value.id;
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_select_existing_package",
                [[this.wizId], packageId]
            );
            await this._handleActionResult(res, "Select package");
        } catch (err) {
            this.notification.add(
                _t("Select package failed: %(err)s", {
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
     * Validate the picking. Three-state:
     *   false → guard / no picking → show error
     *   true  → validated, no backorder → refresh
     *   dict  → backorder wizard → doAction; on close, switch to the
     *           newly created backorder and refresh.
     */
    async onValidatePicking() {
        if (this.state.scanning || !this.wizId) {
            return;
        }
        this.state.scanning = true;
        try {
            const res = await this.orm.call(
                "wiz.stock.barcodes.picking",
                "action_validate_picking",
                [[this.wizId]]
            );
            if (res === false) {
                await this._refreshState();
                if (["error", "not_found", "more_match"].includes(this.state.message_type)) {
                    this._playAlert();
                }
            } else if (res && typeof res === "object" && res.type) {
                // Backorder confirmation wizard. Once it closes, the
                // backorder picking has been created — switch to it so
                // the operator continues with the remaining quantity.
                await this.actionService.doAction(res, {
                    onClose: async () => {
                        try {
                            await this.orm.call(
                                "wiz.stock.barcodes.picking",
                                "switch_to_backorder_if_any",
                                [[this.wizId]]
                            );
                        } finally {
                            await this._refreshState();
                        }
                    },
                });
            } else {
                // true — validated directly. A backorder may still have
                // been created (e.g. operation type set to "always
                // auto-create backorder"), so try to switch to it.
                try {
                    await this.orm.call(
                        "wiz.stock.barcodes.picking",
                        "switch_to_backorder_if_any",
                        [[this.wizId]]
                    );
                } finally {
                    await this._refreshState();
                }
            }
        } catch (err) {
            this.notification.add(
                _t("Validate failed: %(err)s", {
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

    /**
     * Label of the stack holding lines that are not in any package.
     * Lives in JS (not the template) so ``_t`` extraction picks it up.
     */
    get unpackedName() {
        return _t("Unpacked");
    }

    get barcodePlaceholder() {
        if (this.state.visible_force_add) {
            return _t("Confirm or cancel the new product…");
        }
        return this.state.visible_switch_selector
            ? _t("Select a transfer below…")
            : _t("Scan or type barcode…");
    }

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
            !this.state.visible_force_add &&
            (this.state.product_qty || 0) > 0
        );
    }

    /**
     * Two independent columns for the tablet/desktop masonry layout:
     * even rows go left, odd rows go right. On mobile the columns use
     * ``display: contents`` and each card's inline ``order`` restores the
     * original row sequence.
     */
    get scanColumns() {
        const left = [];
        const right = [];
        (this.state.rows || []).forEach((row, index) => {
            (index % 2 === 0 ? left : right).push(row);
        });
        return [left, right];
    }

    /** Progress bar fill ratio (0-100) for the topbar progress track. */
    get progressPercent() {
        const total = Number(this.state.total_demand) || 0;
        const done = Number(this.state.total_done) || 0;
        if (total <= 0) {
            return 0;
        }
        return Math.max(0, Math.min(100, (done / total) * 100));
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
     * For non-serial products there are no lots, so check picked quantity
     * (mv.quantity > 0) instead of pickedLots.
     */
    get canPutInPack() {
        if (!this.state.show_put_in_pack || !this.state.picking_id) {
            return false;
        }
        const moves = this.state.move_ids || [];
        return moves.some((mv) => mv.quantity > 0 && !mv.package_id);
    }

    /** Step label for the current step index. */
    get currentStepLabel() {
        const steps = this.state.scan_steps || [];
        const s = steps[this.state.step];
        return s ? s.label : "";
    }

    /**
     * Group move rows by stock.move id. The backend splits a single move
     * into multiple rows (one per result_package_id). This groups them back
     * so the product header is rendered once, with all package rows beneath.
     * Each group: { move, rows, totalPicked }
     */
    get groupedMoves() {
        const groups = new Map();
        for (const mv of this.state.move_ids || []) {
            if (!groups.has(mv.id)) {
                groups.set(mv.id, { move: mv, rows: [], totalPicked: 0 });
            }
            const g = groups.get(mv.id);
            g.rows.push(mv);
            g.totalPicked += Number(mv.quantity) || 0;
        }
        return Array.from(groups.values());
    }

    /**
     * Group move rows by result_package (design: one stack per package,
     * product cards inside, package bar at the bottom of the stack).
     * Each group: { key, package_id, package_name, qty, first_row_key,
     *               groups: [{ move, rows, totalPicked }] }
     */
    get groupedByPackage() {
        const pkgs = new Map();
        for (const mv of this.state.move_ids || []) {
            const key = mv.package_id || "nopkg";
            if (!pkgs.has(key)) {
                pkgs.set(key, {
                    key,
                    package_id: mv.package_id || false,
                    package_name: mv.package_name || "",
                    qty: 0,
                    first_row_key: mv.row_key,
                    groups: new Map(),
                });
            }
            const p = pkgs.get(key);
            if (!p.groups.has(mv.id)) {
                p.groups.set(mv.id, {
                    move: mv,
                    rows: [],
                    totalPicked: 0,
                    demandTotal: 0,
                    uomName: mv.uom_name || "",
                    isComplete: false,
                });
            }
            const g = p.groups.get(mv.id);
            g.rows.push(mv);
            const qty = Number(mv.quantity) || 0;
            g.totalPicked += qty;
            g.demandTotal += Number(mv.demand_qty) || 0;
            p.qty += qty;
            // 拣货完成徽章：已拣 >= 需求（需求为 0 的空行不算完成）
            g.isComplete = g.demandTotal > 0 && g.totalPicked >= g.demandTotal;
            if (!g.uomName && mv.uom_name) {
                g.uomName = mv.uom_name;
            }
            // 大数字降档：位数越多字号越小，避免撑破右列压到产品名
            const digits = String(Math.round(g.totalPicked * 100) / 100).length;
            g.pickedNumClass =
                digits >= 7 ? "is-xlong" : digits >= 5 ? "is-long" : "";
        }
        // Unpacked stays on top (design: what is not packed yet — including
        // the unpicked remainder — is always the first stack), packaged
        // stacks keep their scan order below it.
        return Array.from(pkgs.values())
            .sort((a, b) => (a.package_id ? 1 : 0) - (b.package_id ? 1 : 0))
            .map((p) => ({
                ...p,
                groups: Array.from(p.groups.values()),
            }));
    }

    /** Props for the native Odoo CogMenu component rendered in the
     *  top-right corner. Items come from the picking form's toolbar
     *  (scrap / print reports / lock / split / etc.) — exactly what the
     *  user would see on the stock.picking form view, so the UI and
     *  behaviour are 100% native Odoo. */
    get cogMenuProps() {
        const items = this.state.action_menu_items || {};
        return {
            resModel: "stock.picking",
            getActiveIds: () => (this.state.picking_id ? [this.state.picking_id] : []),
            context: this.props.context || {},
            items: {
                action: items.action || [],
                print: items.print || [],
            },
            isDomainSelected: false,
        };
    }

    // ---------- serial card collapse (local UI only) ----------

    onToggleSerialFold(rowKey) {
        const map = { ...this.state.expandedSerialRows };
        map[rowKey] = !map[rowKey];
        this.state.expandedSerialRows = map;
    }

    isSerialCollapsed(rowKey) {
        return !this.state.expandedSerialRows[rowKey];
    }

    /**
     * Collapsed serial card shows the last scanned lot (falling back to
     * the latest picked lot, then the first lot) plus the picked total.
     */
    getSerialCollapseSummary(mv) {
        if (!mv.lots || !mv.lots.length) {
            return false;
        }
        let lot = false;
        const recentKey = this.state.recentScanLotKey;
        if (recentKey && recentKey.startsWith(mv.row_key + ":")) {
            const lotId = Number(recentKey.slice(mv.row_key.length + 1));
            lot = mv.lots.find((l) => l.id === lotId) || false;
        }
        if (!lot && mv.latest_lot_id) {
            lot = mv.lots.find((l) => l.id === mv.latest_lot_id) || false;
        }
        if (!lot) {
            lot = mv.lots[0];
        }
        const total = mv.lots.reduce(
            (sum, l) => sum + (Number(l.picked_quantity) || 0),
            0
        );
        return { name: lot.name, total };
    }
}

registry
    .category("actions")
    .add("stock_barcodes_picking.PickingScanApp", PickingScanApp);
