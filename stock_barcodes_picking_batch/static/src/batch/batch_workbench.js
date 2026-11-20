// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { useService } from "@web/core/utils/hooks";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";

const SERVICE = "stock.barcodes.workbench";
const PAGE_SIZE = 80;

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
    in_progress: { label: "进行中", color: "ongoing" },
    done: { label: "已完成", color: "done_today" },
};

export class BatchWorkbench extends Component {
    static template = "stock_barcodes_picking_batch.BatchWorkbench";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        const params = (this.props.action && this.props.action.params) || {};
        this.batchId = params.batch_id || false;
        this.addMode = params.mode === "add" && Boolean(this.batchId);
        this.state = useState({
            view: "list",
            scanValue: "",
            batches: [],
            facets: [],
            stateFilter: "all",
            page: 1,
            pageSize: PAGE_SIZE,
            total: 0,
            types: [],
            createTypeId: false,
            candidates: [],
            pickPage: 1,
            batch: false,
            selectedIds: [],
            loading: false,
            warehouses: [],
            warehouseLabel: "",
            warehouseMenuOpen: false,
            warehouseLocked: false,
            selectedWarehouseId: false,
            user: { name: "", time: "" },
        });
        // See the picking workbench: a bfcache restore after the browser
        // back button would keep a dead UI; reload instead.
        this._onPageShow = (event) => {
            if (event.persisted) {
                window.location.reload();
            }
        };
        window.addEventListener("pageshow", this._onPageShow);
        document.body.classList.remove("o_apps_menu_opened");
        onWillUnmount(() => {
            window.removeEventListener("pageshow", this._onPageShow);
        });
        onMounted(async () => {
            if (this.addMode) {
                this.state.view = "pick";
                await this._loadBatchAndCandidates();
            } else {
                await this._loadHeader();
                await this._loadList();
            }
        });
    }

    // ---------- getters ----------

    get batchRows() {
        return this.state.batches;
    }

    get rows() {
        return this.state.candidates;
    }

    get selectedCount() {
        return this.state.selectedIds.length;
    }

    get pageLabel() {
        if (!this.state.total) {
            return "0 / 0";
        }
        const start = (this.state.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.page * this.state.pageSize, this.state.total);
        return `${start}-${end} / ${this.state.total}`;
    }

    get canPrev() {
        return this.state.page > 1;
    }

    get canNext() {
        return this.state.page * this.state.pageSize < this.state.total;
    }

    get pickPageLabel() {
        if (!this.state.candidates.length) {
            return "0 / 0";
        }
        const start = (this.state.pickPage - 1) * PAGE_SIZE + 1;
        const end = Math.min(
            this.state.pickPage * PAGE_SIZE,
            this.state.candidates.length
        );
        return `${start}-${end} / ${this.state.candidates.length}`;
    }

    get pickRows() {
        const start = (this.state.pickPage - 1) * PAGE_SIZE;
        return this.state.candidates.slice(start, start + PAGE_SIZE);
    }

    get canPickPrev() {
        return this.state.pickPage > 1;
    }

    get canPickNext() {
        return this.state.pickPage * PAGE_SIZE < this.state.candidates.length;
    }

    get pickTitle() {
        if (this.addMode) {
            return "加单";
        }
        const type = this.state.types.find(
            (item) => item.id === this.state.createTypeId
        );
        return type ? type.name : "单据选择";
    }

    statusLabel(key) {
        return STATUS_META[key] ? STATUS_META[key].label : key;
    }

    statusColor(key) {
        return STATUS_META[key] ? STATUS_META[key].color : "draft";
    }

    batchStateLabel(state) {
        return this.statusLabel(state);
    }

    batchStateColor(state) {
        return this.statusColor(state);
    }

    isSelected(candidate) {
        return this.state.selectedIds.includes(candidate.id);
    }

    // ---------- loading ----------

    async _loadHeader() {
        try {
            const data = await this.orm.call(SERVICE, "get_workbench_data", [
                this.state.selectedWarehouseId || false,
            ]);
            this.state.warehouses = data.warehouses || [];
            this.state.user = data.user || { name: "", time: "" };
            const selected = data.selected_warehouse;
            if (selected) {
                this.state.selectedWarehouseId = selected.id;
                this.state.warehouseLabel =
                    `主仓库 ${selected.name}`;
            }
        } catch (error) {
            this._notifyError("加载仓库失败", error);
        }
    }

    async _loadList() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(SERVICE, "get_batch_list", [
                this.state.selectedWarehouseId || false,
                this.state.stateFilter,
                this.state.page,
                this.state.pageSize,
            ]);
            this.state.batches = data.records || [];
            this.state.facets = data.facets || [];
            this.state.total = data.total || 0;
            this.state.pageSize = data.page_size || PAGE_SIZE;
            this.state.view = "list";
        } catch (error) {
            this._notifyError("加载批量调拨失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadTypes() {
        this.state.loading = true;
        try {
            this.state.types = await this.orm.call(
                SERVICE,
                "get_batch_create_types",
                [this.state.selectedWarehouseId || false]
            );
            const preferred =
                this.state.types.find((type) => type.count > 0) ||
                this.state.types[0];
            this.state.createTypeId = preferred ? preferred.id : false;
            this.state.candidates = [];
            this.state.selectedIds = [];
            this.state.pickPage = 1;
            this.state.view = "types";
        } catch (error) {
            this._notifyError("加载作业类型失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadCandidates() {
        if (!this.state.createTypeId) {
            this.state.candidates = [];
            return;
        }
        this.state.loading = true;
        try {
            this.state.candidates = await this.orm.call(
                SERVICE,
                "get_batch_candidates",
                [this.state.selectedWarehouseId || false, this.state.createTypeId]
            );
            this.state.selectedIds = [];
            this.state.pickPage = 1;
        } catch (error) {
            this._notifyError("加载单据失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    async _loadBatchAndCandidates() {
        this.state.loading = true;
        try {
            this.state.batch = await this.orm.call(SERVICE, "get_batch_info", [
                this.batchId,
            ]);
            this.state.warehouseLocked = true;
            this.state.warehouseLabel = this.state.batch.warehouse
                ? `主仓库 ${this.state.batch.warehouse}`
                : "";
            this.state.candidates = await this.orm.call(
                SERVICE,
                "get_add_candidates",
                [this.batchId]
            );
            this.state.selectedIds = [];
            this.state.pickPage = 1;
        } catch (error) {
            this._notifyError("加载待办单据失败", error);
        } finally {
            this.state.loading = false;
        }
    }

    _notifyError(prefix, error) {
        const message =
            (error && (error.data && error.data.message || error.message)) ||
            String(error);
        this.notification.add(`${prefix}：${message}`, { type: "danger" });
    }

    // ---------- actions ----------

    async onBack() {
        if (this.state.view === "pick") {
            if (this.addMode) {
                this.env.config.historyBack();
                return;
            }
            this.state.view = "types";
            this.state.selectedIds = [];
            return;
        }
        if (this.state.view === "types") {
            this.state.view = "list";
            this.state.selectedIds = [];
            this.state.warehouseLocked = false;
            this.state.warehouseMenuOpen = false;
            await this._loadList();
            return;
        }
        // Replace this controller with the workbench instead of pushing a
        // new one; pushing grew the URL stack (.../767/777/767/777...).
        await this.actionService.doAction(
            "stock_barcodes_picking.action_scan_workbench",
            { stackPosition: "replaceCurrentAction" }
        );
    }

    onCreateView() {
        this.state.warehouseLocked = true;
        this.state.warehouseMenuOpen = false;
        this._loadTypes();
    }

    onToggleWarehouseMenu() {
        if (this.state.warehouseLocked) {
            return;
        }
        this.state.warehouseMenuOpen = !this.state.warehouseMenuOpen;
    }

    onCloseWarehouseMenu() {
        this.state.warehouseMenuOpen = false;
    }

    async onSelectWarehouse(warehouseId) {
        this.state.warehouseMenuOpen = false;
        if (warehouseId === this.state.selectedWarehouseId) {
            return;
        }
        this.state.selectedWarehouseId = warehouseId;
        const warehouse = this.state.warehouses.find(
            (item) => item.id === warehouseId
        );
        this.state.warehouseLabel = warehouse
            ? `主仓库 ${warehouse.name}`
            : "";
        this.state.page = 1;
        await this._loadList();
    }

    async onSelectType(type) {
        if (this.state.createTypeId === type.id && this.state.candidates.length) {
            this.state.view = "pick";
            return;
        }
        this.state.createTypeId = type.id;
        this.state.pickPage = 1;
        await this._loadCandidates();
        this.state.view = "pick";
    }

    onSelectStateFilter(facet) {
        this.state.stateFilter = facet.key;
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

    onPrevPickPage() {
        if (this.canPickPrev) {
            this.state.pickPage -= 1;
        }
    }

    onNextPickPage() {
        if (this.canPickNext) {
            this.state.pickPage += 1;
        }
    }

    async onOpenBatch(batch) {
        try {
            const action = await this.orm.call(
                SERVICE,
                "get_batch_scan_action",
                [batch.id]
            );
            await this.actionService.doAction(action);
        } catch (error) {
            this._notifyError("打开批次失败", error);
        }
    }

    async _handleBarcode(barcode) {
        const value = (barcode || "").trim();
        if (!value) {
            return;
        }
        try {
            const result = await this.orm.call(SERVICE, "scan_batch_barcode", [
                value,
                false,
            ]);
            if (result.action === "open_batch") {
                await this.onOpenBatch({ id: result.batch_id });
                return;
            }
            if (result.action === "choose") {
                const names = (result.candidates || [])
                    .map((candidate) => candidate.name)
                    .join("、");
                this.notification.add(`找到多个批次：${names}`, {
                    type: "warning",
                });
                return;
            }
            this.notification.add(result.message || "未找到批次", {
                type: "danger",
            });
        } catch (error) {
            this._notifyError("扫描批次失败", error);
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

    onToggleCandidate(candidate) {
        const index = this.state.selectedIds.indexOf(candidate.id);
        if (index === -1) {
            this.state.selectedIds.push(candidate.id);
        } else {
            this.state.selectedIds.splice(index, 1);
        }
    }

    async onCreateBatch() {
        if (!this.state.selectedIds.length) {
            this.notification.add("请先选择要加入批量的单据", { type: "warning" });
            return;
        }
        try {
            const result = await this.orm.call(SERVICE, "create_batch", [
                this.state.selectedWarehouseId || false,
                this.state.createTypeId,
                this.state.selectedIds,
            ]);
            this.notification.add(`已创建批次 ${result.name}`, {
                type: "success",
            });
            await this.actionService.doAction(result.action);
        } catch (error) {
            this._notifyError("创建批次失败", error);
        }
    }

    async onAddToBatch() {
        if (!this.state.selectedIds.length) {
            this.notification.add("请先选择要加入的单据", { type: "warning" });
            return;
        }
        try {
            await this.orm.call(SERVICE, "add_pickings_to_batch", [
                this.batchId,
                this.state.selectedIds,
            ]);
            this.notification.add(
                `已加入 ${this.state.selectedIds.length} 张单据`,
                { type: "success" }
            );
            this.env.config.historyBack();
        } catch (error) {
            this._notifyError("加入批次失败", error);
        }
    }

    onSubmitCandidates() {
        if (this.addMode) {
            return this.onAddToBatch();
        }
        return this.onCreateBatch();
    }
}

registry
    .category("actions")
    .add("stock_barcodes_picking_batch.BatchWorkbench", BatchWorkbench);
