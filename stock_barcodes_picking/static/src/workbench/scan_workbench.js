// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import {
    Component,
    onMounted,
    onPatched,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

/**
 * Scan workbench.
 *
 * Design: Pixso file QCYzTmFbRuUHHkLF-fg7TA, page 7:1188.
 *   - workbench: frame 52:5192
 *   - status entry list: frame 52:8364
 *   - operation-type entry list: frame 52:8352
 *
 * Data comes from the table-less service model
 * ``stock.barcodes.workbench`` (P2). The IA card is a virtual entry: it has
 * no stock.picking.type and opens the inventory count page in P4.
 */

const SERVICE = "stock.barcodes.workbench";
const DEFAULT_PAGE_SIZE = 80;
// sessionStorage key holding the exact workbench list coordinates so a
// browser-back from the fullscreen scan action can restore the list the
// operator came from. The scan action is a separate client action; going back
// reloads this one from the URL, which carries only the action id, so runtime
// state (listKind / filter / page / warehouse) must survive in storage.
const WB_RETURN_KEY = "stock_barcodes_wb_return";
const WB_RETURN_TTL = 30 * 60 * 1000;
// Marker on a synthetic history entry that stands for the "list" screen.
// The list is only an internal state.view of this action (not its own Odoo
// action), so without its own history entry a system/browser back from the
// list would pop the whole workbench action and land on the apps menu.
const WB_LIST_SENTINEL = "__wbListSentinel";

const STATUS_META = {
    all: { label: "所有", color: "all" },
    draft: { label: "草稿", color: "draft" },
    confirmed: { label: "等待", color: "confirmed" },
    waiting_other: { label: "等待其他作业", color: "waiting_other" },
    ready: { label: "就绪", color: "ready" },
    done_today: { label: "今日已完成", color: "done_today" },
    overdue: { label: "逾期", color: "overdue" },
    cancel: { label: "已取消", color: "cancel" },
    ongoing: { label: "进行中", color: "ongoing" },
};

export class ScanWorkbench extends Component {
    static template = "stock_barcodes_picking.ScanWorkbench";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");
        this.statsStrip = useRef("statsStrip");
        this.filtersStrip = useRef("filtersStrip");
        this._onResize = () => this.updateStripOverflow();
        this.state = useState({
            view: "workbench",
            warehouses: [],
            selectedWarehouseId: false,
            warehouseLabel: "",
            user: { name: "", time: "" },
            warehouseMenuOpen: false,
            scanValue: "",
            selectedRowId: 0,
            page: 1,
            pageSize: DEFAULT_PAGE_SIZE,
            recentPage: 1,
            listKind: "status",
            listKey: "all",
            filterValue: "all",
            stats: [],
            homeStats: [],
            webResponsive: false,
            types: [],
            recent: [],
            rows: [],
            facets: [],
            total: 0,
            listTitleText: "",
            listSubtitleText: "",
            listDomain: [],
            inventoryQuants: [],
            inventoryPending: 0,
            inventoryFilterLabel: "",
            inventoryApplying: false,
            loading: false,
            statsNav: { overflow: false, left: false, right: false },
            filtersNav: { overflow: false, left: false, right: false },
        });
        // Going home and pressing the browser back button can restore this
        // fullscreen action from the back-forward cache with dead timers /
        // bus connections, which looks like a frozen page. Force a clean
        // reload in that case.
        this._onPageShow = (event) => {
            if (event.persisted) {
                window.location.reload();
            }
        };
        window.addEventListener("pageshow", this._onPageShow);
        document.body.classList.remove("o_apps_menu_opened");
        // Restore the list view when returning from the fullscreen scan action.
        // The back navigation reloads this action from the URL, so we replay
        // the list coordinates captured in _rememberListForReturn() instead of
        // landing on a fresh workbench home.
        this._restoreListFromReturn();
        // The list view owns a synthetic history entry (see _pushListSentinel).
        // When a system/browser back lands on the plain workbench entry while
        // we are still showing the list, fall back to the home view instead of
        // letting the next back pop the whole action into the apps menu.
        this._onWbPopState = () => {
            let sentinel = false;
            try {
                sentinel = !!(browser.history.state || {})[WB_LIST_SENTINEL];
            } catch {
                sentinel = false;
            }
            if (!sentinel && this.state.view === "list") {
                this.state.view = "workbench";
                this.state.warehouseMenuOpen = false;
            }
        };
        browser.addEventListener("popstate", this._onWbPopState);
        onMounted(() => {
            this.updateStripOverflow();
            browser.addEventListener("resize", this._onResize);
            if (this.state.view === "list") {
                // Also load base data (warehouse name / types) so the list
                // header is complete; _applyWorkbenchData never touches view.
                this._loadWorkbench();
                this._loadList();
            } else {
                this._loadWorkbench();
            }
        });
        onPatched(() => this.updateStripOverflow());
        onWillUnmount(() => {
            window.removeEventListener("pageshow", this._onPageShow);
            browser.removeEventListener("resize", this._onResize);
            browser.removeEventListener("popstate", this._onWbPopState);
        });
    }

    // ---------- getters ----------

    get stats() {
        return this.state.stats;
    }

    get homeStats() {
        return this.state.homeStats.length
            ? this.state.homeStats
            : this.state.stats.slice(0, 4);
    }

    get types() {
        return this.state.types;
    }

    get recentRows() {
        return this.state.recent;
    }

    get recentPageLabel() {
        const count = this.state.recent.length;
        if (!count) {
            return "0 / 0";
        }
        return `1-${count} / ${count}`;
    }

    get warehouses() {
        return this.state.warehouses;
    }

    get listTitle() {
        if (this.state.listTitleText) {
            return this.state.listTitleText;
        }
        return this.state.listKind === "status"
            ? this.statusLabel(this.state.listKey)
            : "";
    }

    get listSubtitle() {
        return this.state.listSubtitleText;
    }

    get filterTitle() {
        return this.state.listKind === "status" ? "作业类型" : "状态";
    }

    get facets() {
        return this.state.facets;
    }

    get filteredRows() {
        return this.state.rows;
    }

    get inventoryRows() {
        return this.state.inventoryQuants;
    }

    get inventoryDirtyCount() {
        return this.state.inventoryQuants.filter((quant) => quant.dirty).length;
    }

    get total() {
        return this.state.total;
    }

    get pageLabel() {
        return this._pageLabel(this.state.page, this.state.total);
    }

    get canPrev() {
        return this.state.page > 1;
    }

    get canNext() {
        return this.state.page * this.state.pageSize < this.state.total;
    }

    // ---------- helpers ----------

    _pageLabel(page, total) {
        if (!total) {
            return "0 / 0";
        }
        const size = this.state.pageSize || DEFAULT_PAGE_SIZE;
        const start = (page - 1) * size + 1;
        const end = Math.min(page * size, total);
        return `${start}-${end} / ${total}`;
    }

    statusLabel(key) {
        return STATUS_META[key] ? STATUS_META[key].label : key;
    }

    statusColor(key) {
        return STATUS_META[key] ? STATUS_META[key].color : "draft";
    }

    // ---------- horizontal strips (mouse users need explicit arrows) ----------

    updateStripOverflow() {
        this._updateStrip("statsStrip", "statsNav");
        this._updateStrip("filtersStrip", "filtersNav");
    }

    _updateStrip(refName, stateKey) {
        const el = this[refName] ? this[refName].el : null;
        let next;
        if (!el) {
            next = { overflow: false, left: false, right: false };
        } else {
            const overflow = el.scrollWidth > el.clientWidth + 1;
            next = {
                overflow,
                left: overflow && el.scrollLeft > 1,
                right:
                    overflow &&
                    el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
            };
        }
        const current = this.state[stateKey];
        if (
            current.overflow !== next.overflow ||
            current.left !== next.left ||
            current.right !== next.right
        ) {
            this.state[stateKey] = next;
        }
    }

    scrollStrip(refName, direction) {
        const el = this[refName] ? this[refName].el : null;
        if (!el) {
            return;
        }
        el.scrollBy({
            left:
                direction *
                Math.max(140, Math.round(el.clientWidth * 0.9)),
            behavior: "smooth",
        });
    }

    // ---------- return-from-scan state ----------

    /**
     * Push one synthetic history entry that represents the list view as its
     * own layer. The list is only an internal state.view of this action, so
     * without this a system/browser back from the list would pop the entire
     * workbench action and land on the apps menu, skipping the home view.
     *
     * We reuse the current router URL and nextState (so Odoo still restores
     * this same action) and just tag the state with a sentinel flag. Back from
     * a deeper action (scan/form) lands on this entry, where the one-shot
     * snapshot restores the list; a further back lands on the plain workbench
     * entry and _onWbPopState switches the view back to home.
     */
    _pushListSentinel() {
        // Idempotent: repeated navigation into the list must not pile up
        // duplicate history entries.
        if (this._listSentinelActive()) {
            return;
        }
        try {
            const cur = browser.history.state || {};
            browser.history.pushState(
                { ...cur, [WB_LIST_SENTINEL]: true },
                "",
                browser.location.href
            );
        } catch {
            // History API unavailable: degrade to the old behaviour.
        }
    }

    /** Whether the current history entry is our list sentinel. */
    _listSentinelActive() {
        try {
            return !!(browser.history.state || {})[WB_LIST_SENTINEL];
        } catch {
            return false;
        }
    }

    /**
     * Capture the current list coordinates right before leaving for the
     * fullscreen scan action. The scan action lives in a different client
     * action; coming back reloads this workbench from the URL with only the
     * action id, so these coordinates must live in sessionStorage. Only save
     * while the list view is actually showing — opening a scan from the home
     * page (recent card / scan box) must not fake a list to return to.
     */
    _rememberListForReturn() {
        if (this.state.view !== "list") {
            return;
        }
        try {
            browser.sessionStorage.setItem(
                WB_RETURN_KEY,
                JSON.stringify({
                    view: "list",
                    listKind: this.state.listKind,
                    listKey: this.state.listKey,
                    filterValue: this.state.filterValue,
                    page: this.state.page,
                    selectedWarehouseId: this.state.selectedWarehouseId || false,
                    t: Date.now(),
                })
            );
        } catch {
            // Private mode / storage full: degrade to the workbench home.
        }
    }

    /**
     * Replay a previously captured list view on mount. Consumes the snapshot
     * (one-shot) and ignores stale entries so a much later plain visit to the
     * workbench does not unexpectedly reopen an old list.
     */
    _restoreListFromReturn() {
        let saved = null;
        try {
            const raw = browser.sessionStorage.getItem(WB_RETURN_KEY);
            browser.sessionStorage.removeItem(WB_RETURN_KEY);
            saved = raw ? JSON.parse(raw) : null;
        } catch {
            saved = null;
        }
        if (!saved || saved.view !== "list") {
            return;
        }
        if (Date.now() - (saved.t || 0) >= WB_RETURN_TTL) {
            return;
        }
        this.state.view = "list";
        this.state.listKind = saved.listKind || "status";
        this.state.listKey = String(saved.listKey ?? "all");
        this.state.filterValue = saved.filterValue || "all";
        this.state.page = saved.page || 1;
        this.state.selectedWarehouseId = saved.selectedWarehouseId || false;
        this.state.selectedRowId = 0;
    }

    // ---------- loading ----------

    async _loadWorkbench() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(SERVICE, "get_workbench_data", [
                this.state.selectedWarehouseId || false,
            ]);
            this._applyWorkbenchData(data);
        } catch (error) {
            this._notifyError("加载工作台失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    _applyWorkbenchData(data) {
        this.state.warehouses = data.warehouses || [];
        if (data.selected_warehouse) {
            this.state.selectedWarehouseId = data.selected_warehouse.id;
            this.state.warehouseLabel = data.selected_warehouse.name;
        }
        this.state.user = data.user || { name: "", time: "" };
        this.state.stats = data.stats || [];
        this.state.homeStats = data.home_stats || [];
        this.state.webResponsive = Boolean(data.web_responsive);
        this.state.types = data.types || [];
        this.state.recent = data.recent || [];
    }

    async _loadList() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(SERVICE, "get_workbench_list", [
                this.state.selectedWarehouseId || false,
                this.state.listKind,
                String(this.state.listKey),
                String(this.state.filterValue),
                this.state.page,
                this.state.pageSize,
            ]);
            this.state.rows = data.records || [];
            this.state.facets = data.facets || [];
            this.state.total = data.total || 0;
            this.state.pageSize = data.page_size || DEFAULT_PAGE_SIZE;
            this.state.listTitleText = data.title || "";
            this.state.listSubtitleText = data.subtitle || "";
            this.state.listDomain = data.domain || [];
        } catch (error) {
            this._notifyError("加载单据列表失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    _notifyError(prefix, error) {
        const message =
            (error && (error.data && error.data.message || error.message)) ||
            String(error);
        // Navigating away destroys this component; an in-flight load that
        // resolves afterwards is expected to fail this way and must not pop
        // an error toast on the page we just opened.
        if (String(message).includes("Component is destroyed")) {
            return;
        }
        this.notification.add(`${prefix}：${message}`, { type: "danger" });
    }

    async _loadInventory() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                SERVICE,
                "get_inventory_scan_data",
                [this.state.selectedWarehouseId || false]
            );
            this.state.inventoryPending = data.pending_count || 0;
            this.state.inventoryFilterLabel = "";
            this._applyInventoryQuants(data.quants || []);
        } catch (error) {
            this._notifyError("加载盘点数据失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    _applyInventoryQuants(quants) {
        this.state.inventoryQuants = quants.map((quant) => ({
            ...quant,
            editValue: "",
            dirty: false,
            diffLabel: "0",
        }));
    }

    // ---------- actions ----------

    onOpenList(kind, key, action) {
        if (action) {
            this.actionService.doAction(action);
            return;
        }
        if (kind === "type" && key === "ia") {
            this.state.view = "inventory";
            this.state.selectedRowId = 0;
            this._loadInventory();
            return;
        }
        this.state.view = "list";
        this.state.listKind = kind;
        this.state.listKey = String(key);
        this.state.filterValue = "all";
        this.state.page = 1;
        this.state.selectedRowId = 0;
        this.state.listTitleText = "";
        this.state.listSubtitleText = "";
        this.state.rows = [];
        this.state.facets = [];
        this.state.total = 0;
        // Give the list its own history layer so a system back returns here
        // (via the one-shot snapshot) instead of skipping the whole action.
        this._pushListSentinel();
        this._loadList();
    }

    async onRefreshWorkbench() {
        await this._loadWorkbench();
    }

    /**
     * Back to the function-selection (apps) screen.
     *
     * Do NOT toggle the Web Responsive "redirect home" preference: it made
     * the apps overlay auto-open on top of scan/form pages. Instead go to
     * /odoo and let open_apps_menu.js click the apps-grid button once the
     * navbar is mounted.
     */
    async onGoHome() {
        sessionStorage.setItem("scan_open_apps_menu", "1");
        window.location.href = "/odoo";
    }

    onBack() {
        const wasInventory = this.state.view === "inventory";
        const wasList = this.state.view === "list";
        this.state.view = "workbench";
        this.state.warehouseMenuOpen = false;
        if (wasInventory) {
            this._loadWorkbench();
        }
        if (wasList && this._listSentinelActive()) {
            // Consume the synthetic list history entry as well, so the next
            // system back goes straight to the apps menu instead of replaying
            // the list layer. The view is already switched above, so the
            // popstate handler will not flip it a second time.
            browser.history.back();
        }
    }

    async onNewPicking() {
        const typeId = Number(this.state.listKey);
        if (!typeId) {
            return;
        }
        try {
            const action = await this.orm.call(SERVICE, "create_empty_picking", [
                this.state.selectedWarehouseId || false,
                typeId,
            ]);
            // doAction unmounts this workbench, so nothing may touch state or
            // call the ORM afterwards (Odoo rejects it with "Component is
            // destroyed"). The list reloads by itself when we navigate back.
            await this.actionService.doAction(action);
        } catch (error) {
            this._notifyError("新建调拨失败", error);
        }
    }

    onClearInventoryFilter() {
        this._loadInventory();
    }

    onInventoryQtyInput(quant, ev) {
        const value = ev.target.value;
        quant.editValue = value;
        quant.dirty = value !== "";
        if (value === "") {
            quant.diffLabel = "0";
            return;
        }
        const number = parseFloat(value);
        if (Number.isNaN(number)) {
            quant.diffLabel = "-";
            return;
        }
        const diff = Math.round((number - quant.quantity) * 1000) / 1000;
        quant.diff = diff;
        quant.diffLabel = diff > 0 ? `+${diff}` : String(diff);
    }

    async onApplyInventory() {
        const entries = this.state.inventoryQuants
            .filter((quant) => quant.dirty && quant.editValue !== "")
            .map((quant) => ({
                quant_id: quant.id,
                quantity: quant.editValue,
            }));
        if (!entries.length) {
            this.notification.add("没有需要应用的盘点数量", {
                type: "warning",
            });
            return;
        }
        this.state.inventoryApplying = true;
        try {
            const result = await this.orm.call(SERVICE, "apply_inventory", [
                entries,
                this.state.selectedWarehouseId || false,
            ]);
            this.notification.add(`已应用 ${result.applied} 行盘点`, {
                type: "success",
            });
            await this._loadInventory();
            await this._loadWorkbench();
        } catch (error) {
            this._notifyError("应用盘点失败", error);
        } finally {
            this.state.inventoryApplying = false;
        }
    }

    onSelectFilter(facet) {
        this.state.filterValue = String(facet.key);
        this.state.page = 1;
        this._loadList();
    }

    onPrevPage() {
        if (this.canPrev) {
            this.state.page -= 1;
            this._loadList();
        }
    }

    onNextPage() {
        if (this.canNext) {
            this.state.page += 1;
            this._loadList();
        }
    }

    async onToggleStar(row) {
        const next = !row.starred;
        try {
            await this.orm.call(SERVICE, "toggle_star", [row.id, next]);
            row.starred = next;
        } catch (error) {
            this._notifyError("更新收藏失败", error);
        }
    }

    async onOpenPicking(row) {
        this.state.selectedRowId = row.id;
        await this._openPicking(row.id, row.state, row.name);
    }

    async _openPicking(pickingId, pickingState, pickingName) {
        // Remember the list we are leaving so a browser-back from the scan
        // action restores it instead of dumping us on the workbench home.
        this._rememberListForReturn();
        try {
            await this.orm.call(SERVICE, "mark_recent", [pickingId]);
            if (pickingState === "done" || pickingState === "cancel") {
                await this.actionService.doAction({
                    type: "ir.actions.act_window",
                    name: pickingName,
                    res_model: "stock.picking",
                    res_id: pickingId,
                    views: [[false, "form"]],
                    target: "current",
                });
                return;
            }
            const action = await this.orm.call(
                "stock.picking",
                "action_barcode_scan",
                [[pickingId]]
            );
            await this.actionService.doAction(action);
        } catch (error) {
            this._notifyError("打开单据失败", error);
        }
    }

    async _handleBarcode(barcode) {
        const value = (barcode || "").trim();
        if (!value) {
            return;
        }
        try {
            if (this.state.view === "inventory") {
                const result = await this.orm.call(
                    SERVICE,
                    "scan_inventory_barcode",
                    [value, this.state.selectedWarehouseId || false]
                );
                if (result.action === "error") {
                    this.notification.add(
                        result.message || "未找到待盘点的库存",
                        { type: "danger" }
                    );
                    return;
                }
                this.state.inventoryFilterLabel = value;
                this._applyInventoryQuants(result.candidates || []);
                return;
            }
            const result = await this.orm.call(
                SERVICE,
                "scan_workbench_barcode",
                [value, this.state.selectedWarehouseId || false]
            );
            if (result.action === "open_picking") {
                await this._openPicking(result.picking_id);
                return;
            }
            if (result.action === "choose") {
                this._choosePicking(result.picking_ids || []);
                return;
            }
            this.notification.add(
                result.message || "未找到匹配的单据",
                { type: "danger" }
            );
        } catch (error) {
            this._notifyError("扫码失败", error);
        }
    }

    _choosePicking(pickingIds) {
        if (!pickingIds.length) {
            return;
        }
        this.dialogService.add(SelectCreateDialog, {
            resModel: "stock.picking",
            title: "选择单据",
            multiSelect: false,
            noCreate: true,
            domain: [["id", "in", pickingIds]],
            onSelected: (resIds) => {
                const pickingId = resIds && resIds[0];
                if (pickingId) {
                    this._openPicking(pickingId);
                }
            },
        });
    }

    onToggleWarehouseMenu() {
        this.state.warehouseMenuOpen = !this.state.warehouseMenuOpen;
    }

    onCloseWarehouseMenu() {
        this.state.warehouseMenuOpen = false;
    }

    async onSelectWarehouse(warehouseId) {
        this.state.warehouseMenuOpen = false;
        try {
            const data = await this.orm.call(SERVICE, "select_warehouse", [
                warehouseId,
            ]);
            this._applyWorkbenchData(data);
            if (this.state.view === "list") {
                this.state.page = 1;
                await this._loadList();
            } else if (this.state.view === "inventory") {
                await this._loadInventory();
            }
        } catch (error) {
            this._notifyError("切换仓库失败", error);
        }
    }

    async onScanKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const value = (this.state.scanValue || "").trim();
        if (!value) {
            return;
        }
        this.state.scanValue = "";
        await this._handleBarcode(value);
    }

    async onCamera() {
        try {
            const barcode = await scanBarcode(this.env, "environment");
            if (barcode && barcode.trim()) {
                await this._handleBarcode(barcode.trim());
            }
        } catch (error) {
            this._notifyError("相机扫码失败", error);
        }
    }

    async onFunnel() {
        try {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                name: this.listTitle,
                res_model: "stock.picking",
                view_mode: "list,kanban,form",
                views: [
                    [false, "list"],
                    [false, "kanban"],
                    [false, "form"],
                ],
                domain: this.state.listDomain,
                target: "current",
            });
        } catch (error) {
            this._notifyError("打开原生筛选失败", error);
        }
    }
}

registry
    .category("actions")
    .add("stock_barcodes_picking.ScanWorkbench", ScanWorkbench);
