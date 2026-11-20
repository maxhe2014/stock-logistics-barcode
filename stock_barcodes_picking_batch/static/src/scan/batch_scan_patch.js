// Copyright 2026 OpenViking
// License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PickingScanApp } from "@stock_barcodes_picking/picking_scan_app";

patch(PickingScanApp.prototype, {
    setup() {
        super.setup();
        Object.assign(this.state, {
            batch_id: false,
            batch_name: "",
            batch_state: "",
            batch_picking_count: 0,
        });
    },

    /** Batch mode validates the whole batch, so the button must stay
     *  available even when the currently displayed picking is finished. */
    get canValidate() {
        if (this.state.batch_id) {
            return !["done", "cancel"].includes(this.state.batch_state);
        }
        return super.canValidate;
    },

    /** The cog menu must drive the batch form (and its print report). */
    get cogMenuProps() {
        if (!this.state.batch_id) {
            return super.cogMenuProps;
        }
        const items = this.state.action_menu_items || {};
        return {
            resModel: "stock.picking.batch",
            getActiveIds: () => [this.state.batch_id],
            context: this.props.context || {},
            items: {
                action: items.action || [],
                print: items.print || [],
            },
            isDomainSelected: false,
        };
    },

    /** The big yellow document button opens the batch in batch mode. */
    async onOpenPicking() {
        if (!this.state.batch_id) {
            return super.onOpenPicking();
        }
        return this.actionService.doAction({
            res_model: "stock.picking.batch",
            res_id: this.state.batch_id,
            views: [[false, "form"]],
            type: "ir.actions.act_window",
            target: "current",
        });
    },

    /** Validate the whole batch. */
    async onValidatePicking() {
        if (!this.state.batch_id) {
            return super.onValidatePicking();
        }
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
                if (
                    ["error", "not_found", "more_match"].includes(
                        this.state.message_type
                    )
                ) {
                    this._playAlert();
                }
                return;
            }
            if (res && typeof res === "object" && res.type) {
                await this.actionService.doAction(res);
            }
            await this._refreshState();
            if (this.state.batch_state === "done") {
                this.env.config.historyBack();
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
    },

    /** "更多…" → 加单: pick more transfers for the current batch. */
    async onBatchAddPickings() {
        if (!this.state.batch_id) {
            return;
        }
        await this.actionService.doAction({
            type: "ir.actions.client",
            tag: "stock_barcodes_picking_batch.BatchWorkbench",
            params: { batch_id: this.state.batch_id, mode: "add" },
        });
    },
});
