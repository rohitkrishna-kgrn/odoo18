/** @odoo-module */
const { Component } = owl;
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRef, useState } from "@odoo/owl";
import { BlockUI } from "@web/core/ui/block_ui";
import { download } from "@web/core/network/download";
import { formatFloat } from "@web/core/utils/numbers";

const actionRegistry = registry.category("actions");
const today = luxon.DateTime.now();
const MODEL = "age.receivable.report";

class AgedReceivablePM extends owl.Component {

    async setup() {
        super.setup(...arguments);
        this.orm        = useService("orm");
        this.action     = useService("action");
        this.tbody      = useRef("tbody");
        this.date_range = useRef("date_to");
        this.date_from  = useRef("date_from");

        this.state = useState({
            // ── flat-mode (partner-grouped) data ──
            move_line:   null,
            data:        null,
            total:       null,
            currency:    null,
            total_debit: null,
            total_debit_display: null,
            diff0_sum: null, diff0_sum_display: null,
            diff1_sum: null, diff1_sum_display: null,
            diff2_sum: null, diff2_sum_display: null,
            diff3_sum: null, diff3_sum_display: null,
            diff4_sum: null, diff4_sum_display: null,
            diff5_sum: null, diff5_sum_display: null,

            // ── PM-grouped data ──
            grouped:   false,
            pm_list:   [],
            pm_data:   null,
            pm_totals: null,
            grand_total: null,

            // ── filters ──
            selected_partner:     [],
            selected_partner_rec: [],
            selected_pm:          [],
            selected_pm_rec:      [],
            pm_options:           [],
            group_by_pm:          false,

            // ── UI state ──
            pm_filter_open:  false,
            group_by_open:   false,
        });

        // Load available PMs once
        this.state.pm_options = await this.orm.call(MODEL, "get_pm_list", []);
        await this._loadData();
    }

    // ----------------------------------------------------------------
    // Data loading
    // ----------------------------------------------------------------

    _currentDate() {
        return this.date_range.el ? this.date_range.el.value : "";
    }
    _currentDateFrom() {
        return this.date_from.el ? this.date_from.el.value : "";
    }

    async _loadData() {
        try {
            const result = await this.orm.call(MODEL, "get_pm_report_data", [
                this._currentDate(),
                this.state.selected_partner,
                this.state.selected_pm,
                this.state.group_by_pm,
                this._currentDateFrom(),
            ]);
            if (result.grouped) {
                this._applyGrouped(result);
            } else {
                this._applyFlat(result);
            }
        } catch (e) {
            console.error("AgedReceivablePM: failed to load data", e);
        }
    }

    _applyFlat(result) {
        const moveLineList = [];
        let moveLinesTotal = {};
        let d0 = 0, d1 = 0, d2 = 0, d3 = 0, d4 = 0, d5 = 0, tot = 0, currency;

        for (const [key, val] of Object.entries(result)) {
            if (key !== "partner_totals") {
                moveLineList.push(key);
            } else {
                moveLinesTotal = val;
                for (const ml of Object.values(val)) {
                    currency = ml.currency_id;
                    d0  += ml.diff0_sum || 0;
                    d1  += ml.diff1_sum || 0;
                    d2  += ml.diff2_sum || 0;
                    d3  += ml.diff3_sum || 0;
                    d4  += ml.diff4_sum || 0;
                    d5  += ml.diff5_sum || 0;
                    tot += ml.debit_sum || 0;
                }
            }
        }

        Object.assign(this.state, {
            grouped:   false,
            move_line: moveLineList,
            data:      result,
            total:     moveLinesTotal,
            currency,
            total_debit:          tot,
            total_debit_display:  formatFloat(tot,  { digits: [0, 2] }),
            diff0_sum: d0, diff0_sum_display: formatFloat(d0, { digits: [0, 2] }),
            diff1_sum: d1, diff1_sum_display: formatFloat(d1, { digits: [0, 2] }),
            diff2_sum: d2, diff2_sum_display: formatFloat(d2, { digits: [0, 2] }),
            diff3_sum: d3, diff3_sum_display: formatFloat(d3, { digits: [0, 2] }),
            diff4_sum: d4, diff4_sum_display: formatFloat(d4, { digits: [0, 2] }),
            diff5_sum: d5, diff5_sum_display: formatFloat(d5, { digits: [0, 2] }),
        });
    }

    _applyGrouped(result) {
        const gt = result.grand_total || {};
        Object.assign(this.state, {
            grouped:     true,
            pm_list:     result.pm_list     || [],
            pm_data:     result.pm_data     || {},
            pm_totals:   result.pm_totals   || {},
            grand_total: gt,
            currency:    result.currency,
            total_debit:         gt.debit_sum || 0,
            total_debit_display: formatFloat(gt.debit_sum || 0, { digits: [0, 2] }),
            diff0_sum: gt.diff0_sum || 0, diff0_sum_display: formatFloat(gt.diff0_sum || 0, { digits: [0, 2] }),
            diff1_sum: gt.diff1_sum || 0, diff1_sum_display: formatFloat(gt.diff1_sum || 0, { digits: [0, 2] }),
            diff2_sum: gt.diff2_sum || 0, diff2_sum_display: formatFloat(gt.diff2_sum || 0, { digits: [0, 2] }),
            diff3_sum: gt.diff3_sum || 0, diff3_sum_display: formatFloat(gt.diff3_sum || 0, { digits: [0, 2] }),
            diff4_sum: gt.diff4_sum || 0, diff4_sum_display: formatFloat(gt.diff4_sum || 0, { digits: [0, 2] }),
            diff5_sum: gt.diff5_sum || 0, diff5_sum_display: formatFloat(gt.diff5_sum || 0, { digits: [0, 2] }),
        });
    }

    // ----------------------------------------------------------------
    // Navigation helpers
    // ----------------------------------------------------------------

    gotoJournalEntry(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    gotoJournalItem(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move.line",
            name: "Journal Items",
            views: [[false, "list"]],
            domain: [
                ["partner_id", "=", parseInt(ev.target.attributes["data-id"].value, 10)],
                ["account_type", "in", ["asset_receivable"]],
            ],
            target: "current",
        });
    }

    openPartner(ev) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: parseInt(ev.target.attributes["data-id"].value, 10),
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ----------------------------------------------------------------
    // Unfold all
    // ----------------------------------------------------------------

    async unfoldAll(ev) {
        const cls = "selected-filter";
        const children = this.tbody.el.children;
        if (!ev.target.classList.contains(cls)) {
            for (let i = 0; i < children.length; i++) children[i].classList.add("show");
            ev.target.classList.add(cls);
        } else {
            for (let i = 0; i < children.length; i++) children[i].classList.remove("show");
            ev.target.classList.remove(cls);
        }
    }

    // ----------------------------------------------------------------
    // Date / quick-filter
    // ----------------------------------------------------------------

    async applyDateFilter(ev) {
        const v = ev.target.attributes["data-value"] && ev.target.attributes["data-value"].value;
        if (v === "today")            this.date_range.el.value = today.toFormat("yyyy-MM-dd");
        else if (v === "last-month-end")
            this.date_range.el.value = today.startOf("month").minus({ days: 1 }).toFormat("yyyy-MM-dd");
        else if (v === "last-quarter-end")
            this.date_range.el.value = today.startOf("quarter").minus({ days: 1 }).toFormat("yyyy-MM-dd");
        else if (v === "last-year-end")
            this.date_range.el.value = today.startOf("year").minus({ days: 1 }).toFormat("yyyy-MM-dd");
        await this._loadData();
    }

    async onDateInput() {
        await this._loadData();
    }

    // ----------------------------------------------------------------
    // PM filter
    // ----------------------------------------------------------------

    togglePmFilter() {
        this.state.pm_filter_open = !this.state.pm_filter_open;
    }

    async selectPm(pm) {
        const already = this.state.selected_pm.includes(pm.id);
        if (!already) {
            this.state.selected_pm.push(pm.id);
            this.state.selected_pm_rec.push(pm);
        }
        this.state.pm_filter_open = false;
        await this._loadData();
    }

    async removePm(pm) {
        this.state.selected_pm     = this.state.selected_pm.filter(id => id !== pm.id);
        this.state.selected_pm_rec = this.state.selected_pm_rec.filter(p => p.id !== pm.id);
        await this._loadData();
    }

    // ----------------------------------------------------------------
    // Group By PM toggle
    // ----------------------------------------------------------------

    async toggleGroupByPm() {
        this.state.group_by_pm = !this.state.group_by_pm;
        await this._loadData();
    }

    // ----------------------------------------------------------------
    // Filters payload (for PDF / XLSX)
    // ----------------------------------------------------------------

    _filters() {
        return {
            partner:    this.state.selected_partner_rec,
            pm:         this.state.selected_pm_rec,
            end_date:   this._currentDate(),
            start_date: this._currentDateFrom(),
            group_by_pm: this.state.group_by_pm,
        };
    }

    // ----------------------------------------------------------------
    // PDF print
    // ----------------------------------------------------------------

    async printPdf() {
        const totals = {
            diff0_sum: this.state.diff0_sum, diff0_sum_display: this.state.diff0_sum_display,
            diff1_sum: this.state.diff1_sum, diff1_sum_display: this.state.diff1_sum_display,
            diff2_sum: this.state.diff2_sum, diff2_sum_display: this.state.diff2_sum_display,
            diff3_sum: this.state.diff3_sum, diff3_sum_display: this.state.diff3_sum_display,
            diff4_sum: this.state.diff4_sum, diff4_sum_display: this.state.diff4_sum_display,
            diff5_sum: this.state.diff5_sum, diff5_sum_display: this.state.diff5_sum_display,
            total_debit: this.state.total_debit, total_debit_display: this.state.total_debit_display,
            currency: this.state.currency,
        };

        return this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "dynamic_accounts_report.aged_receivable_pm",
            report_file: "dynamic_accounts_report.aged_receivable_pm",
            data: {
                move_lines:    this.state.move_line,
                data:          this.state.data,
                total:         this.state.total,
                filters:       this._filters(),
                grand_total:   totals,
                // grouped-mode specific
                grouped:       this.state.grouped,
                pm_list:       this.state.pm_list,
                pm_data:       this.state.pm_data,
                pm_totals:     this.state.pm_totals,
                pm_grand_total: this.state.grand_total,
                title:          this.props.action.display_name,
                report_name:    this.props.action.display_name,
            },
            display_name: this.props.action.display_name,
        });
    }

    // ----------------------------------------------------------------
    // XLSX export
    // ----------------------------------------------------------------

    async print_xlsx() {
        const totals = {
            diff0_sum: this.state.diff0_sum,
            diff1_sum: this.state.diff1_sum,
            diff2_sum: this.state.diff2_sum,
            diff3_sum: this.state.diff3_sum,
            diff4_sum: this.state.diff4_sum,
            diff5_sum: this.state.diff5_sum,
            total_debit: this.state.total_debit,
        };
        const payload = {
            move_lines:  this.state.move_line,
            data:        this.state.data,
            total:       this.state.total,
            filters:     this._filters(),
            grand_total: this.state.grouped ? this.state.grand_total : totals,
            grouped:     this.state.grouped,
            pm_list:     this.state.pm_list,
            pm_data:     this.state.pm_data,
            pm_totals:   this.state.pm_totals,
        };
        const action = {
            data: {
                model: MODEL,
                data:  JSON.stringify(payload),
                output_format: "xlsx",
                report_action: "dynamic_accounts_report.action_aged_receivable_pm",
                report_name:   this.props.action.display_name,
            },
        };
        BlockUI;
        await download({
            url: "/xlsx_report",
            data: action.data,
            complete: () => {},
            error: (err) => console.error(err),
        });
    }
}

AgedReceivablePM.template = "age_r_pm_template";
AgedReceivablePM.defaultProps = { resIds: [] };
actionRegistry.add("age_r_pm", AgedReceivablePM);
