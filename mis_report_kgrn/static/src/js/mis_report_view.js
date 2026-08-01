/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { formatMonetary, formatFloat, formatInteger } from "@web/views/fields/formatters";

// Dialog showing the sales & delivery revenue breakdown for one employee-month.
export class MisRevenueBreakdownDialog extends Component {
    static components = { Dialog };
    static template = "mis_report_kgrn.MisRevenueBreakdownDialog";
    static props = {
        close: Function,
        title: String,
        sales: Array,
        delivery: Array,
        salesTotal: Number,
        deliveryTotal: Number,
        currencyId: { type: [Number, Boolean], optional: true },
    };
    money(v) {
        return formatMonetary(v || 0, { currencyId: this.props.currencyId });
    }
    num(v) {
        return formatFloat(v || 0, { digits: [16, 2] });
    }
}

/* ─────────────────────────────────────────────────────────────────────────
 * Report configurations — one per menu.
 * type: char | integer | float | monetary | date | boolean | m2o
 * agg:  true  → summed in group subtotals & grand total
 * open: model name → the m2o cell becomes clickable and opens that record
 * ──────────────────────────────────────────────────────────────────────── */
const REPORT_CONFIGS = {
    // ── Project Wise ────────────────────────────────────────────────────
    mis_project_wise: {
        resModel: "mis.project.wise",
        title: "Project Wise Report",
        currencyField: "currency_id",
        decorationField: "is_completed",
        searchFields: ["project_name", "so_number"],
        titleFields: ["project_id", "so_number"],
        dateFilters: [
            { field: "project_create_date", label: "Created" },
            { field: "deadline", label: "Deadline" },
            { field: "last_invoice_date", label: "Invoice Date" },
        ],
        // When both bounds of "Invoice Date" are set, recompute Invoiced/Paid
        // restricted to that exact range (and Outstanding as of the "to" date)
        // via the server, instead of showing lifetime cumulative totals.
        periodRecompute: {
            dateField: "last_invoice_date",
            method: "get_period_amounts",
            columns: [
                "invoiced_ex_vat", "invoiced_inc_vat",
                "paid_ex_vat", "paid_inc_vat",
                "outstanding_ex_vat", "outstanding_inc_vat",
            ],
        },
        groupBy: [
            { field: "company_id", label: "Company" },
            { field: "department_id", label: "Department" },
            { field: "project_manager_id", label: "Project Manager" },
            { field: "customer_id", label: "Customer" },
            { field: "salesperson_id", label: "Salesperson" },
            { field: "sale_order_id", label: "Sale Order" },
        ],
        defaultGroupBy: ["company_id", "department_id", "project_manager_id"],
        columns: [
            { name: "company_id", label: "Company", type: "m2o" },
            { name: "department_id", label: "Department", type: "m2o" },
            { name: "project_manager_id", label: "Project Manager", type: "m2o" },
            { name: "project_id", label: "Project", type: "m2o", open: "project.project" },
            { name: "customer_id", label: "Customer", type: "m2o" },
            { name: "sale_order_id", label: "Sale Order", type: "m2o", open: "sale.order" },
            { name: "salesperson_id", label: "Salesperson", type: "m2o" },
            { name: "deadline", label: "Deadline", type: "date" },
            { name: "days_overdue", label: "Days Overdue", type: "integer" },
            { name: "product_uom_qty", label: "Ordered Qty", type: "float" },
            { name: "qty_delivered", label: "Delivered Qty", type: "float" },
            { name: "so_total_ex_vat", label: "SO Total (Ex VAT)", type: "monetary", agg: true },
            { name: "invoiced_ex_vat", label: "Invoiced (Ex VAT)", type: "monetary", agg: true },
            { name: "paid_ex_vat", label: "Paid (Ex VAT)", type: "monetary", agg: true },
            { name: "outstanding_ex_vat", label: "Outstanding (Ex VAT)", type: "monetary", agg: true },
            { name: "advance_amount", label: "Advance (SO)", type: "monetary" },
            { name: "last_invoice_date", label: "Last Invoice", type: "date" },
            { name: "is_completed", label: "Completed", type: "boolean" },
        ],
        // Extra fields shown only on the form (not in the list).
        formFieldDefs: {
            so_number: { label: "SO Number", type: "char" },
            sale_order_line_id: { label: "SO Line", type: "m2o" },
            unit_value_ex_vat: { label: "Unit Value (Ex VAT)", type: "monetary" },
            unit_value_inc_vat: { label: "Unit Value (Inc VAT)", type: "monetary" },
            delivered_value_ex_vat: { label: "Delivered Value (Ex VAT)", type: "monetary" },
            delivered_value_inc_vat: { label: "Delivered Value (Inc VAT)", type: "monetary" },
            so_total_inc_vat: { label: "SO Total (Inc VAT)", type: "monetary" },
            sol_price_subtotal: { label: "Line Total (Ex VAT)", type: "monetary" },
            sol_price_total: { label: "Line Total (Inc VAT)", type: "monetary" },
            invoiced_inc_vat: { label: "Invoiced (Inc VAT)", type: "monetary" },
            paid_inc_vat: { label: "Paid (Inc VAT)", type: "monetary" },
            outstanding_inc_vat: { label: "Outstanding (Inc VAT)", type: "monetary" },
            advance_per_line: { label: "Advance (This Line)", type: "monetary" },
            invoice_days_ago: { label: "Invoice (Days Ago)", type: "integer" },
            project_create_date: { label: "Created Date", type: "date" },
        },
        form: [
            {
                title: "Project",
                fields: ["company_id", "department_id", "project_manager_id",
                         "project_id", "customer_id", "salesperson_id"],
            },
            {
                title: "Sale Order",
                fields: ["sale_order_id", "so_number", "sale_order_line_id",
                         "product_uom_qty", "qty_delivered"],
            },
            {
                title: "Unit & Delivered Values",
                fields: ["unit_value_ex_vat", "unit_value_inc_vat",
                         "delivered_value_ex_vat", "delivered_value_inc_vat",
                         "sol_price_subtotal", "sol_price_total",
                         "so_total_ex_vat", "so_total_inc_vat"],
            },
            {
                title: "Invoicing",
                fields: ["invoiced_ex_vat", "invoiced_inc_vat",
                         "paid_ex_vat", "paid_inc_vat",
                         "outstanding_ex_vat", "outstanding_inc_vat",
                         "advance_amount", "advance_per_line"],
            },
            {
                title: "Dates & Status",
                fields: ["deadline", "days_overdue", "last_invoice_date",
                         "invoice_days_ago", "project_create_date", "is_completed"],
            },
        ],
    },

    // ── Outstanding ─────────────────────────────────────────────────────
    mis_outstanding: {
        resModel: "mis.outstanding.line",
        title: "Outstanding Report",
        currencyField: "currency_id",
        decorationField: "is_completed",
        searchFields: ["project_name", "so_number"],
        titleFields: ["project_id", "so_number"],
        dateFilters: [
            { field: "project_create_date", label: "Created" },
            { field: "deadline", label: "Deadline" },
            { field: "last_invoice_date", label: "Invoice Date" },
        ],
        groupBy: [
            { field: "company_id", label: "Company" },
            { field: "department_id", label: "Department" },
            { field: "project_manager_id", label: "Project Manager" },
            { field: "customer_id", label: "Customer" },
            { field: "salesperson_id", label: "Salesperson" },
        ],
        defaultGroupBy: ["company_id", "department_id", "project_manager_id"],
        columns: [
            { name: "company_id", label: "Company", type: "m2o" },
            { name: "department_id", label: "Department", type: "m2o" },
            { name: "project_manager_id", label: "Project Manager", type: "m2o" },
            { name: "project_id", label: "Project", type: "m2o", open: "project.project" },
            { name: "customer_id", label: "Customer", type: "m2o" },
            { name: "sale_order_id", label: "SO", type: "m2o", open: "sale.order" },
            { name: "salesperson_id", label: "Salesperson", type: "m2o" },
            { name: "deadline", label: "Deadline", type: "date" },
            { name: "days_overdue", label: "Days Overdue", type: "integer" },
            { name: "project_value_ex_vat", label: "Project Value (Ex VAT)", type: "monetary", agg: true },
            { name: "so_total_ex_vat", label: "SO Total (Ex VAT)", type: "monetary", agg: true },
            { name: "advance_amount", label: "Advance (SO)", type: "monetary" },
            { name: "tasks_total", label: "Total Tasks", type: "integer", agg: true },
            { name: "tasks_completed", label: "Completed Tasks", type: "integer", agg: true },
            { name: "tasks_pending", label: "Pending Tasks", type: "integer", agg: true },
            { name: "completed_invoiced_amount", label: "Completed & Paid", type: "monetary", agg: true },
            { name: "completed_posted_not_paid_amount", label: "Posted Not Paid", type: "monetary", agg: true },
            { name: "completed_not_invoiced_amount", label: "No Invoice", type: "monetary", agg: true },
            { name: "last_invoice_date", label: "Last Invoice", type: "date" },
            { name: "invoice_days_ago", label: "Invoice (Days Ago)", type: "integer" },
        ],
        formFieldDefs: {
            so_number: { label: "SO Number", type: "char" },
            project_value_inc_vat: { label: "Project Value (Inc VAT)", type: "monetary" },
            so_total_inc_vat: { label: "SO Total (Inc VAT)", type: "monetary" },
            completed_tasks_value_ex_vat: { label: "Completed Tasks Value (Ex VAT)", type: "monetary" },
            completed_invoiced_qty: { label: "Completed & Paid (Qty)", type: "integer" },
            completed_posted_not_paid_qty: { label: "Posted Not Paid (Qty)", type: "integer" },
            completed_not_invoiced_qty: { label: "No Invoice (Qty)", type: "integer" },
            project_create_date: { label: "Created Date", type: "date" },
        },
        form: [
            {
                title: "Project",
                fields: ["company_id", "department_id", "project_manager_id",
                         "project_id", "customer_id", "salesperson_id"],
            },
            {
                title: "Sale Order & Value",
                fields: ["sale_order_id", "so_number",
                         "project_value_ex_vat", "project_value_inc_vat",
                         "so_total_ex_vat", "so_total_inc_vat", "advance_amount"],
            },
            {
                title: "Tasks",
                fields: ["tasks_total", "tasks_completed", "tasks_pending",
                         "completed_tasks_value_ex_vat"],
            },
            {
                title: "Invoice Buckets",
                fields: ["completed_invoiced_qty", "completed_invoiced_amount",
                         "completed_posted_not_paid_qty", "completed_posted_not_paid_amount",
                         "completed_not_invoiced_qty", "completed_not_invoiced_amount"],
            },
            {
                title: "Dates & Status",
                fields: ["deadline", "days_overdue", "last_invoice_date",
                         "invoice_days_ago", "project_create_date", "is_completed"],
            },
        ],
    },

    // ── Project Revenue (task-level + employee detail) ──────────────────
    mis_project_revenue: {
        resModel: "mis.project.revenue",
        title: "Task Revenue",
        currencyField: "currency_id",
        searchFields: ["task_name"],
        titleFields: ["task_id"],
        dateFilters: [{ field: "task_create_date", label: "Created" }],
        groupBy: [
            { field: "company_id", label: "Company" },
            { field: "department_id", label: "Department" },
            { field: "project_manager_id", label: "Project Manager" },
            { field: "project_id", label: "Project" },
        ],
        defaultGroupBy: ["department_id", "project_id"],
        columns: [
            { name: "company_id", label: "Company", type: "m2o" },
            { name: "department_id", label: "Department", type: "m2o" },
            { name: "project_manager_id", label: "Project Manager", type: "m2o" },
            { name: "project_id", label: "Project", type: "m2o", open: "project.project" },
            { name: "sale_order_id", label: "Sale Order", type: "m2o", open: "sale.order" },
            { name: "task_id", label: "Task", type: "m2o", open: "project.task" },
            { name: "task_value", label: "Task Unit Value", type: "monetary" },
            { name: "total_employee_revenue", label: "Total Employee Revenue", type: "monetary", agg: true },
            { name: "total_weighted_hours", label: "Total Weighted Hrs", type: "float" },
        ],
        formFieldDefs: {
            task_name: { label: "Task Name", type: "char" },
            sale_order_line_id: { label: "SO Line", type: "m2o" },
            task_create_date: { label: "Task Created Date", type: "date" },
        },
        form: [
            {
                title: "Task Details",
                fields: ["company_id", "department_id", "project_manager_id",
                         "project_id", "sale_order_id", "task_id", "task_name",
                         "task_create_date"],
            },
            {
                title: "Revenue Calculation",
                fields: ["sale_order_line_id", "task_value",
                         "total_weighted_hours", "total_employee_revenue"],
            },
        ],
        detail: {
            title: "Employee Revenue Breakdown",
            model: "mis.project.revenue.line",
            parentField: "task_revenue_id",
            columns: [
                { name: "user_id", label: "Employee", type: "m2o" },
                { name: "mis_revenue_role_id", label: "MIS Role", type: "m2o" },
                { name: "role_multiplier", label: "Multiplier", type: "float" },
                { name: "actual_hours", label: "Actual Hours", type: "float" },
                { name: "weighted_hours", label: "Weighted Hours", type: "float" },
                { name: "value_per_weighted_hour", label: "Value / Weighted Hr", type: "monetary" },
                { name: "employee_revenue", label: "Employee Revenue", type: "monetary" },
            ],
        },
    },
};

// ── Performance Management dashboards (shared shape, filtered by team) ──
function makePerformanceConfig(team, title) {
    return {
        resModel: "mis.performance.line",
        title,
        currencyField: "currency_id",
        decorationField: "is_met",
        revenueBreakdown: true,
        baseDomain: [["performance_team", "=", team]],
        searchFields: ["employee_name", "escalation_stage"],
        titleFields: ["employee_id", "period_label"],
        dateFilters: [{ field: "period_date", label: "Month" }],
        groupBy: [
            { field: "department_id", label: "Department" },
            { field: "employee_id", label: "Employee" },
            { field: "office_location", label: "Office" },
            { field: "escalation_stage", label: "Escalation Stage" },
        ],
        defaultGroupBy: ["department_id", "employee_id"],
        columns: [
            { name: "department_id", label: "Department", type: "m2o" },
            { name: "employee_id", label: "Employee", type: "m2o", open: "hr.employee" },
            { name: "office_location", label: "Office", type: "char" },
            { name: "period_label", label: "Month", type: "char" },
            { name: "monthly_ctc", label: "Monthly CTC", type: "monetary", currency: "ctc_currency_id" },
            { name: "monthly_obligation", label: "Obligation", type: "monetary", currency: "ctc_currency_id" },
            { name: "sales_revenue", label: "Sales Revenue", type: "monetary", agg: true },
            { name: "delivery_revenue", label: "Delivery Revenue", type: "monetary", agg: true },
            { name: "total_revenue", label: "Total Revenue", type: "monetary", agg: true },
            { name: "achievement_pct", label: "Achievement", type: "percent" },
            { name: "is_met", label: "Met", type: "boolean" },
            { name: "escalation_stage", label: "Escalation Stage", type: "char" },
        ],
        formFieldDefs: {
            employee_name: { label: "Employee", type: "char" },
            performance_team: { label: "Team", type: "char" },
            user_id: { label: "User", type: "m2o" },
            annual_ctc: { label: "Annual CTC", type: "monetary", currency: "ctc_currency_id" },
            annual_target: { label: "Annual Target", type: "monetary", currency: "ctc_currency_id" },
            consecutive_non_perf: { label: "Consecutive Non-Perf Months", type: "integer" },
            period_date: { label: "Month (date)", type: "date" },
        },
        form: [
            {
                title: "Employee",
                fields: ["employee_id", "department_id", "performance_team",
                         "office_location", "user_id", "period_label"],
            },
            {
                title: "Cost & Targets",
                fields: ["monthly_ctc", "annual_ctc",
                         "monthly_obligation", "annual_target"],
            },
            {
                title: "Revenue (this month)",
                fields: ["sales_revenue", "delivery_revenue",
                         "total_revenue", "achievement_pct"],
            },
            {
                title: "Status & Escalation",
                fields: ["is_met", "consecutive_non_perf", "escalation_stage"],
            },
        ],
    };
}
REPORT_CONFIGS.mis_performance_sales = makePerformanceConfig("sales", "Sales Performance");
REPORT_CONFIGS.mis_performance_operations = makePerformanceConfig("operations", "Operations Performance");
REPORT_CONFIGS.mis_performance_other = makePerformanceConfig("other", "Other Teams Performance");

export class MisReportView extends Component {
    static template = "mis_report_kgrn.MisReportView";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");

        const tag = this.props.action?.tag || this.props.actionTag;
        this.config = REPORT_CONFIGS[tag];
        if (!this.config) {
            throw new Error(`MIS Report: unknown config for tag "${tag}"`);
        }

        this.columns = this.config.columns;

        // Build a lookup of every field definition (list columns + form-only).
        this._fieldDefMap = {};
        for (const col of this.columns) {
            this._fieldDefMap[col.name] = col;
        }
        for (const [name, def] of Object.entries(this.config.formFieldDefs || {})) {
            this._fieldDefMap[name] = { name, ...def };
        }

        this.state = useState({
            view: "list",        // 'list' | 'form'
            record: null,        // record shown in form
            loading: true,
            allRecords: [],
            tree: [],
            leaves: [],
            totals: {},
            count: 0,
            groupBy: [...this.config.defaultGroupBy],
            search: "",
            dates: Object.fromEntries(
                this.config.dateFilters.map((d) => [d.field, { from: "", to: "" }])
            ),
            expanded: {},
            detailCache: {},
            periodOverlay: null,
        });

        onWillStart(() => this.load());
    }

    // ── Data loading ─────────────────────────────────────────────────────
    get fieldNames() {
        const names = new Set(Object.keys(this._fieldDefMap));
        this.config.searchFields.forEach((f) => names.add(f));
        this.config.dateFilters.forEach((d) => names.add(d.field));
        // per-field currency fields (e.g. ctc_currency_id)
        Object.values(this._fieldDefMap).forEach((d) => d.currency && names.add(d.currency));
        if (this.config.currencyField) names.add(this.config.currencyField);
        if (this.config.decorationField) names.add(this.config.decorationField);
        return [...names];
    }

    async load() {
        this.state.loading = true;
        try {
            const records = await this.orm.searchRead(
                this.config.resModel,
                this.config.baseDomain ? [...this.config.baseDomain] : [],
                this.fieldNames
            );
            this.state.allRecords = records;
            const pr = this.config.periodRecompute;
            if (pr) await this.maybeRecomputePeriod(pr.dateField);
            this.applyFilters();
        } catch (e) {
            console.error("MIS Report load error:", e);
            this.state.allRecords = [];
            this.applyFilters();
        } finally {
            this.state.loading = false;
        }
    }

    // ── Filtering + grouping ─────────────────────────────────────────────
    applyFilters() {
        let recs = this.state.allRecords;

        const term = (this.state.search || "").trim().toLowerCase();
        if (term) {
            recs = recs.filter((r) =>
                this.config.searchFields.some((f) => {
                    const v = r[f];
                    return v && String(v).toLowerCase().includes(term);
                })
            );
        }

        for (const [field, range] of Object.entries(this.state.dates)) {
            if (range.from) recs = recs.filter((r) => r[field] && r[field] >= range.from);
            if (range.to) recs = recs.filter((r) => r[field] && r[field] <= range.to);
        }

        // Overlay period-scoped Invoiced/Paid/Outstanding when active — see
        // maybeRecomputePeriod(). Rows with no invoice/payment activity in
        // the selected range are zeroed out rather than left at their
        // lifetime totals.
        const pr = this.config.periodRecompute;
        if (pr && this.state.periodOverlay) {
            const overlay = this.state.periodOverlay;
            recs = recs.map((r) => {
                const o = overlay[r.id];
                if (o) return { ...r, ...o };
                const zeroed = { ...r };
                for (const col of pr.columns) zeroed[col] = 0;
                return zeroed;
            });
        }

        this.state.count = recs.length;
        this.state.totals = this.aggregate(recs);

        if (this.state.groupBy.length) {
            this.state.tree = this.buildTree(recs, this.state.groupBy, "");
            this.state.leaves = [];
        } else {
            this.state.tree = [];
            this.state.leaves = recs;
        }
    }

    buildTree(records, groupFields, parentPath) {
        const [field, ...rest] = groupFields;
        const map = new Map();
        for (const rec of records) {
            const v = rec[field];
            const key = Array.isArray(v) ? v[0] : v === false ? "__none__" : v;
            const label = Array.isArray(v) ? v[1] : v === false ? "None" : String(v);
            if (!map.has(key)) map.set(key, { key, label, records: [] });
            map.get(key).records.push(rec);
        }
        const nodes = [];
        for (const g of map.values()) {
            const path = `${parentPath}/${field}:${g.key}`;
            const node = {
                path,
                field,
                key: g.key,
                label: g.label,
                count: g.records.length,
                records: g.records,
                aggregates: this.aggregate(g.records),
            };
            if (rest.length) {
                node.children = this.buildTree(g.records, rest, path);
            } else {
                node.leaves = g.records;
            }
            nodes.push(node);
        }
        nodes.sort((a, b) => String(a.label).localeCompare(String(b.label)));
        return nodes;
    }

    aggregate(records) {
        const totals = {};
        for (const col of this.columns) {
            if (col.agg) {
                totals[col.name] = records.reduce(
                    (s, r) => s + (Number(r[col.name]) || 0),
                    0
                );
            }
        }
        return totals;
    }

    // ── Toolbar handlers ─────────────────────────────────────────────────
    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.applyFilters();
    }

    async onDateChange(field, bound, ev) {
        this.state.dates[field][bound] = ev.target.value;
        await this.maybeRecomputePeriod(field);
        this.applyFilters();
    }

    // Fetch period-scoped Invoiced/Paid/Outstanding from the server whenever
    // both bounds of the configured period field are set; otherwise fall
    // back to the lifetime totals already loaded on each record.
    async maybeRecomputePeriod(changedField) {
        const pr = this.config.periodRecompute;
        if (!pr || changedField !== pr.dateField) return;

        const range = this.state.dates[pr.dateField];
        if (range.from && range.to) {
            const ids = this.state.allRecords.map((r) => r.id);
            this.state.periodOverlay = await this.orm.call(
                this.config.resModel,
                pr.method,
                [ids, range.from, range.to]
            );
        } else {
            this.state.periodOverlay = null;
        }
    }

    toggleGroupBy(field) {
        const idx = this.state.groupBy.indexOf(field);
        if (idx >= 0) {
            // Default groupings are locked — they cannot be removed.
            if (this.isLocked(field)) return;
            this.state.groupBy.splice(idx, 1);
        } else {
            this.state.groupBy.push(field);
        }
        this.state.groupBy = [...this.state.groupBy];
        this.state.expanded = {};
        this.applyFilters();
    }

    isGroupedBy(field) {
        return this.state.groupBy.includes(field);
    }

    isLocked(field) {
        return this.config.defaultGroupBy.includes(field);
    }

    groupByOrder(field) {
        const i = this.state.groupBy.indexOf(field);
        return i >= 0 ? i + 1 : "";
    }

    clearFilters() {
        this.state.search = "";
        for (const field of Object.keys(this.state.dates)) {
            this.state.dates[field] = { from: "", to: "" };
        }
        this.state.periodOverlay = null;
        this.applyFilters();
    }

    // ── Expand / collapse groups ─────────────────────────────────────────
    toggleGroup(path) {
        this.state.expanded[path] = !this.state.expanded[path];
    }

    isExpanded(path) {
        return !!this.state.expanded[path];
    }

    // ── Form navigation ──────────────────────────────────────────────────
    async openForm(rec) {
        this.state.record = rec;
        this.state.view = "form";
        if (this.config.detail && !this.state.detailCache[rec.id]) {
            const det = this.config.detail;
            const fields = det.columns.map((c) => c.name);
            if (this.config.currencyField) fields.push(this.config.currencyField);
            this.state.detailCache[rec.id] = await this.orm.searchRead(
                det.model,
                [[det.parentField, "=", rec.id]],
                fields
            );
        }
    }

    backToList() {
        this.state.view = "list";
        this.state.record = null;
    }

    formTitle(rec) {
        const parts = (this.config.titleFields || [])
            .map((f) => {
                const v = rec[f];
                return Array.isArray(v) ? v[1] : v || "";
            })
            .filter(Boolean);
        return parts.join(" — ") || this.config.title;
    }

    fieldDef(name) {
        return this._fieldDefMap[name] || { name, label: name, type: "char" };
    }

    // ── Formatting helpers ───────────────────────────────────────────────
    currencyId(rec, field) {
        const cf = field || this.config.currencyField;
        return cf && Array.isArray(rec[cf]) ? rec[cf][0] : undefined;
    }

    formatCell(col, rec) {
        // a column may pin its own currency field (e.g. CTC in local currency)
        return this._format(col, rec[col.name], this.currencyId(rec, col.currency));
    }

    formatAgg(col, node) {
        if (!col.agg) return "";
        const cur =
            node.records && node.records.length ? this.currencyId(node.records[0]) : undefined;
        return this._format(col, node.aggregates[col.name], cur);
    }

    formatTotal(col) {
        if (!col.agg) return "";
        const cur =
            this.state.allRecords.length ? this.currencyId(this.state.allRecords[0]) : undefined;
        return this._format(col, this.state.totals[col.name], cur);
    }

    _format(col, value, currencyId) {
        switch (col.type) {
            case "monetary":
                return formatMonetary(value || 0, { currencyId });
            case "float":
                return formatFloat(value || 0, { digits: [16, 2] });
            case "percent":
                return formatFloat(value || 0, { digits: [16, 1] }) + "%";
            case "integer":
                return formatInteger(value || 0);
            case "boolean":
                return value ? "Yes" : "No";
            case "m2o":
                return Array.isArray(value) ? value[1] : "";
            case "date":
                return value || "";
            default:
                return value == null || value === false ? "" : String(value);
        }
    }

    rowClass(rec) {
        const f = this.config.decorationField;
        if (!f) return "";
        return rec[f] ? "o_mis_row_done" : "o_mis_row_pending";
    }

    indent(depth) {
        return `padding-left:${8 + depth * 18}px`;
    }

    openRecord(model, value) {
        if (!Array.isArray(value)) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: value[0],
            views: [[false, "form"]],
            target: "current",
        });
    }

    async openBreakdown(rec) {
        const data = await this.orm.call(
            this.config.resModel,
            "get_revenue_breakdown",
            [
                Array.isArray(rec.employee_id) ? rec.employee_id[0] : rec.employee_id,
                Array.isArray(rec.user_id) ? rec.user_id[0] : rec.user_id || false,
                rec.period_date,
            ]
        );
        this.dialog.add(MisRevenueBreakdownDialog, {
            title: `Revenue Breakdown — ${this.formTitle(rec)}`,
            sales: data.sales || [],
            delivery: data.delivery || [],
            salesTotal: data.sales_total || 0,
            deliveryTotal: data.delivery_total || 0,
            currencyId: this.currencyId(rec),
        });
    }
}

registry.category("actions").add("mis_project_wise", MisReportView);
registry.category("actions").add("mis_outstanding", MisReportView);
registry.category("actions").add("mis_project_revenue", MisReportView);
registry.category("actions").add("mis_performance_sales", MisReportView);
registry.category("actions").add("mis_performance_operations", MisReportView);
registry.category("actions").add("mis_performance_other", MisReportView);
