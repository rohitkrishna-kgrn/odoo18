/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { formatMonetary, formatFloat, formatInteger } from "@web/views/fields/formatters";

// 'YYYY-MM' slice of a 'YYYY-MM-DD' date string — used to compare a
// monthly-bucketed row (e.g. a Performance Management row keyed by the
// 1st of its month) against a selected date range at whole-month
// granularity, so a mid-month "from"/"to" bound still includes/excludes
// exactly the right months.
function rowMonth(dateStr) {
    return dateStr.slice(0, 7);
}

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
            { name: "so_total_ex_vat", label: "SO Total (Ex VAT)", type: "monetary", agg: true, aggDistinct: "sale_order_id" },
            { name: "work_completed_value_ex_vat", label: "Work Completed (Ex VAT)", type: "monetary", agg: true },
            { name: "invoiced_ex_vat", label: "Invoiced (Ex VAT)", type: "monetary", agg: true },
            { name: "paid_ex_vat", label: "Paid (Ex VAT)", type: "monetary", agg: true },
            { name: "outstanding_ex_vat", label: "Outstanding (Ex VAT)", type: "monetary", agg: true },
            { name: "collection_rate", label: "Collection Rate", type: "percent", ratio: ["paid_ex_vat", "invoiced_ex_vat"] },
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
                fields: ["work_completed_value_ex_vat",
                         "invoiced_ex_vat", "invoiced_inc_vat",
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
            { name: "so_total_ex_vat", label: "SO Total (Ex VAT)", type: "monetary", agg: true, aggDistinct: "sale_order_id" },
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

// Selection labels for hr.employee.mis_performance_team — see mis_employee.py.
const PERFORMANCE_TEAM_LABELS = {
    sales: "Sales",
    audit: "Audit",
    tax: "Tax",
    accounting: "Accounting",
    einvoicing: "E-Invoicing",
    other: "Other",
};

// ── Performance Management dashboards (shared shape, filtered by team) ──
// `team` is either one team code ("sales") or an array of codes sharing a
// screen (Operations groups its four sub-teams: Audit / Tax / Accounting /
// E-Invoicing).
function makePerformanceConfig(team, title) {
    const teams = Array.isArray(team) ? team : [team];
    return {
        resModel: "mis.performance.line",
        title,
        currencyField: "currency_id",
        decorationField: "is_met",
        revenueBreakdown: true,
        selectable: true,
        performanceManagementReport: true,
        baseDomain: [["performance_team", "in", teams]],
        // ramp_stage is searchable so typing "Month 1" pulls up every joiner
        // on a reduced target: grouping by it nests under the locked
        // Department/Employee grouping, which is no way to survey them.
        searchFields: ["employee_name", "performance_status", "escalation_stage",
                       "ramp_stage"],
        titleFields: ["employee_id", "period_label"],
        dateFilters: [{ field: "period_date", label: "Date" }],
        // Narrowing (not just grouping) dropdowns. Team is only shown when
        // the screen actually spans more than one team (e.g. Operations).
        selectFilters: [
            ...(teams.length > 1
                ? [{
                      field: "performance_team",
                      label: "Team",
                      options: teams.map((t) => ({ value: t, label: PERFORMANCE_TEAM_LABELS[t] || t })),
                  }]
                : []),
            {
                field: "office_location",
                label: "Office",
                options: [
                    { value: "UAE", label: "UAE" },
                    { value: "India", label: "India" },
                ],
            },
        ],
        // When both bounds are set, recompute Sales/Delivery/Total Revenue
        // restricted to that exact date range (instead of each row's whole
        // calendar month) via the server — same pattern as Project Wise's
        // Invoice Date period recompute. `monthBucket: true` tells the row
        // filter below to keep a row whenever the selected range overlaps
        // its month, not only when its month start falls inside the range.
        periodRecompute: {
            dateField: "period_date",
            monthBucket: true,
            method: "get_period_revenue_amounts",
            columns: ["sales_revenue", "delivery_revenue", "total_revenue",
                      "work_completed_value"],
            hint: "Sales/Delivery/Total Revenue reflect cash collected in this exact date range; Work Delivered reflects work completed in it. Neither covers the full month.",
        },
        groupBy: [
            { field: "department_id", label: "Department" },
            { field: "employee_id", label: "Employee" },
            { field: "office_location", label: "Office" },
            { field: "performance_status", label: "Status" },
            { field: "escalation_stage", label: "Escalation Stage" },
            { field: "ramp_stage", label: "Ramp-up Stage" },
        ],
        defaultGroupBy: ["department_id", "employee_id"],
        columns: [
            { name: "department_id", label: "Department", type: "m2o" },
            { name: "employee_id", label: "Employee", type: "m2o", open: "hr.employee" },
            { name: "office_location", label: "Office", type: "char" },
            { name: "period_label", label: "Month", type: "char" },
            { name: "monthly_ctc", label: "Monthly CTC", type: "monetary", currency: "ctc_currency_id" },
            { name: "monthly_obligation", label: "Obligation", type: "monetary", currency: "ctc_currency_id" },
            // Why the Obligation is reduced — blank-looking low targets on a
            // new joiner are otherwise indistinguishable from a data error.
            { name: "ramp_stage", label: "Ramp-up", type: "char" },
            { name: "work_completed_value", label: "Work Delivered (AED)", type: "monetary", agg: true },
            { name: "invoices_raised_amount", label: "Invoices Raised (AED)", type: "monetary", agg: true },
            { name: "payments_collected_amount", label: "Payments Collected (AED)", type: "monetary", agg: true },
            { name: "sales_revenue", label: "Sales Revenue", type: "monetary", agg: true },
            { name: "delivery_revenue", label: "Delivery Revenue", type: "monetary", agg: true },
            { name: "total_revenue", label: "Total Revenue", type: "monetary", agg: true },
            { name: "achievement_pct", label: "Achievement", type: "percent" },
            { name: "is_met", label: "Met", type: "boolean" },
            { name: "performance_status", label: "Status", type: "char" },
            { name: "escalation_stage", label: "Escalation Stage", type: "char" },
        ],
        formFieldDefs: {
            employee_name: { label: "Employee", type: "char" },
            performance_team: { label: "Team", type: "char" },
            user_id: { label: "User", type: "m2o" },
            annual_ctc: { label: "Annual CTC", type: "monetary", currency: "ctc_currency_id" },
            annual_target: { label: "Annual Target", type: "monetary", currency: "ctc_currency_id" },
            consecutive_non_perf: { label: "Consecutive Non-Perf Months", type: "integer" },
            min_ctc_obligation: { label: "Min. CTC Obligation", type: "monetary", currency: "ctc_currency_id" },
            ramp_stage: { label: "Ramp-up Stage", type: "char" },
            ramp_start_date: { label: "Ramp-up Start", type: "date" },
            months_employed: { label: "Month No.", type: "integer" },
            consecutive_below_target: { label: "Consecutive Below-Target Months", type: "integer" },
            period_date: { label: "Month (date)", type: "date" },
            invoices_raised_count: { label: "Invoices Raised (No.)", type: "integer" },
            invoices_raised_amount: { label: "Invoices Raised (AED)", type: "monetary" },
            payments_collected_amount: { label: "Payments Collected (AED)", type: "monetary" },
            work_completed_value: { label: "Work Delivered (AED)", type: "monetary" },
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
                         "monthly_obligation", "annual_target",
                         "ramp_stage", "ramp_start_date", "months_employed"],
            },
            {
                title: "Revenue (this month)",
                fields: ["sales_revenue", "delivery_revenue",
                         "total_revenue", "achievement_pct"],
            },
            {
                title: "Invoicing & Collection (this month)",
                fields: ["invoices_raised_count", "invoices_raised_amount",
                         "payments_collected_amount"],
            },
            {
                title: "Status & Escalation",
                fields: ["is_met", "consecutive_non_perf",
                         "min_ctc_obligation", "performance_status",
                         "consecutive_below_target", "escalation_stage"],
            },
        ],
    };
}
REPORT_CONFIGS.mis_performance_sales = makePerformanceConfig("sales", "Sales Performance");
REPORT_CONFIGS.mis_performance_operations = makePerformanceConfig(
    ["audit", "tax", "accounting", "einvoicing"], "Operations Performance"
);
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
            selects: Object.fromEntries(
                (this.config.selectFilters || []).map((f) => [f.field, ""])
            ),
            expanded: {},
            detailCache: {},
            periodOverlay: null,
            selected: {},
            expandedBreakdown: {},
            breakdownCache: {},
            breakdownLoading: {},
            expandedProjects: {},
        });

        onWillStart(() => this.load());
    }

    // ── Data loading ─────────────────────────────────────────────────────
    get fieldNames() {
        // Ratio columns (e.g. Collection Rate) are computed client-side from
        // other columns' totals — they aren't real fields on the model, so
        // they must never be sent to the ORM as a field to fetch.
        const names = new Set(
            Object.entries(this._fieldDefMap)
                .filter(([, d]) => !d.ratio)
                .map(([name]) => name)
        );
        this.config.searchFields.forEach((f) => names.add(f));
        this.config.dateFilters.forEach((d) => names.add(d.field));
        (this.config.selectFilters || []).forEach((f) => names.add(f.field));
        // per-field currency fields (e.g. ctc_currency_id)
        Object.values(this._fieldDefMap).forEach((d) => d.currency && names.add(d.currency));
        // dedup keys for order-level aggregates (e.g. SO Total -> sale_order_id)
        Object.values(this._fieldDefMap).forEach((d) => d.aggDistinct && names.add(d.aggDistinct));
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

        const pr0 = this.config.periodRecompute;
        for (const [field, range] of Object.entries(this.state.dates)) {
            const isMonthBucket = pr0 && pr0.dateField === field && pr0.monthBucket;
            if (isMonthBucket) {
                // Month-bucket fields (e.g. Performance's period_date) store
                // the 1st of the month: compare at 'YYYY-MM' granularity so
                // only months whose range actually overlaps [from, to] are
                // kept — a row from a later month must never leak through
                // just because "to" falls mid-month.
                if (range.from) {
                    const fromMonth = rowMonth(range.from);
                    recs = recs.filter((r) => r[field] && rowMonth(r[field]) >= fromMonth);
                }
                if (range.to) {
                    const toMonth = rowMonth(range.to);
                    recs = recs.filter((r) => r[field] && rowMonth(r[field]) <= toMonth);
                }
            } else {
                if (range.from) recs = recs.filter((r) => r[field] && r[field] >= range.from);
                if (range.to) recs = recs.filter((r) => r[field] && r[field] <= range.to);
            }
        }

        for (const [field, value] of Object.entries(this.state.selects)) {
            if (value) recs = recs.filter((r) => r[field] === value);
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
            if (!col.agg) continue;
            if (col.aggDistinct) {
                // Order-level amounts (e.g. SO Total) are carried on every
                // row of the same sale order, so a plain row-by-row sum
                // multiplies a multi-line order by its line count. Count
                // each distinct order once instead. Rows with no key can't
                // be deduplicated, so each one still counts on its own.
                const seen = new Set();
                let sum = 0;
                for (const r of records) {
                    const v = r[col.aggDistinct];
                    const key = Array.isArray(v) ? v[0] : v;
                    if (key !== undefined && key !== null && key !== false) {
                        if (seen.has(key)) continue;
                        seen.add(key);
                    }
                    sum += Number(r[col.name]) || 0;
                }
                totals[col.name] = sum;
            } else {
                totals[col.name] = records.reduce(
                    (s, r) => s + (Number(r[col.name]) || 0),
                    0
                );
            }
        }
        // Ratio columns (e.g. Collection Rate) are group-level weighted
        // rates, not summable — derive from the already-aggregated
        // numerator/denominator totals rather than averaging per-row rates.
        for (const col of this.columns) {
            if (col.ratio) {
                const [numName, denomName] = col.ratio;
                const denom = totals[denomName] || 0;
                totals[col.name] = denom ? (totals[numName] || 0) / denom * 100 : 0;
            }
        }
        return totals;
    }

    // ── Toolbar handlers ─────────────────────────────────────────────────
    onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.applyFilters();
    }

    onDateChange(field, bound, ev) {
        this.state.dates[field][bound] = ev.target.value;
        // Apply the row filter immediately — it only needs local data, so it
        // must never wait on the network. The period-scoped revenue overlay
        // (below) is a separate, slower refinement of a few columns; running
        // it in the background and re-applying filters when it resolves
        // keeps the visible row set from ever depending on how long that
        // request takes.
        this.applyFilters();
        this.maybeRecomputePeriod(field).then(() => this.applyFilters());
    }

    onSelectChange(field, ev) {
        this.state.selects[field] = ev.target.value;
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
        for (const field of Object.keys(this.state.selects)) {
            this.state.selects[field] = "";
        }
        this.state.periodOverlay = null;
        this.applyFilters();
    }

    // ── Row selection (Excel / PDF export) ───────────────────────────────
    visibleLeafRecords() {
        if (!this.state.groupBy.length) return this.state.leaves;
        const out = [];
        const walk = (nodes) => {
            for (const n of nodes) {
                if (n.children) walk(n.children);
                else out.push(...n.leaves);
            }
        };
        walk(this.state.tree);
        return out;
    }

    toggleSelect(id, ev) {
        if (ev) ev.stopPropagation();
        const next = { ...this.state.selected };
        if (next[id]) delete next[id];
        else next[id] = true;
        this.state.selected = next;
    }

    isSelected(id) {
        return !!this.state.selected[id];
    }

    get selectedCount() {
        return Object.keys(this.state.selected).length;
    }

    get totalColspan() {
        return (
            this.columns.length +
            (this.config.selectable ? 1 : 0) +
            (this.config.revenueBreakdown ? 1 : 0)
        );
    }

    toggleSelectAllVisible() {
        const visible = this.visibleLeafRecords();
        const allSelected = visible.length && visible.every((r) => this.state.selected[r.id]);
        const next = { ...this.state.selected };
        for (const r of visible) {
            if (allSelected) delete next[r.id];
            else next[r.id] = true;
        }
        this.state.selected = next;
    }

    isAllVisibleSelected() {
        const visible = this.visibleLeafRecords();
        return !!visible.length && visible.every((r) => this.state.selected[r.id]);
    }

    toggleGroupSelect(node, ev) {
        if (ev) ev.stopPropagation();
        const allSelected = node.records.every((r) => this.state.selected[r.id]);
        const next = { ...this.state.selected };
        for (const r of node.records) {
            if (allSelected) delete next[r.id];
            else next[r.id] = true;
        }
        this.state.selected = next;
    }

    isGroupSelected(node) {
        return node.records.length && node.records.every((r) => this.state.selected[r.id]);
    }

    // ── Inline task / timesheet detail (per employee-month row) ─────────
    // Reuses get_revenue_breakdown, the same server method the form's
    // "Revenue Breakdown" dialog already calls — so the numbers always
    // match, and it automatically respects whichever month a row belongs
    // to (i.e. the current date filter, since rows are pre-filtered).
    async loadBreakdowns(records) {
        const need = records.filter((r) => !this.state.breakdownCache[r.id]);
        if (!need.length) return;
        const items = need.map((r) => ({
            key: String(r.id),
            employee_id: Array.isArray(r.employee_id) ? r.employee_id[0] : r.employee_id,
            user_id: Array.isArray(r.user_id) ? r.user_id[0] : r.user_id || false,
            period_date: r.period_date,
        }));
        const loadingNext = { ...this.state.breakdownLoading };
        for (const it of items) loadingNext[it.key] = true;
        this.state.breakdownLoading = loadingNext;
        const data = await this.orm.call(this.config.resModel, "get_revenue_breakdown_bulk", [items]);
        const cacheNext = { ...this.state.breakdownCache };
        const doneLoading = { ...this.state.breakdownLoading };
        for (const [key, val] of Object.entries(data)) {
            cacheNext[key] = val;
            delete doneLoading[key];
        }
        this.state.breakdownCache = cacheNext;
        this.state.breakdownLoading = doneLoading;
    }

    async toggleBreakdown(rec, ev) {
        if (ev) ev.stopPropagation();
        const next = { ...this.state.expandedBreakdown };
        next[rec.id] = !next[rec.id];
        this.state.expandedBreakdown = next;
        if (next[rec.id]) await this.loadBreakdowns([rec]);
    }

    isBreakdownExpanded(id) {
        return !!this.state.expandedBreakdown[id];
    }

    isBreakdownLoading(id) {
        return !!this.state.breakdownLoading[String(id)];
    }

    breakdownOf(id) {
        return this.state.breakdownCache[id];
    }

    // Delivery detail comes back flat (one row per task); group it by
    // project so the UI (and the Excel export) can show a collapsible
    // Project → Task hierarchy instead of one long task list.
    groupDeliveryByProject(delivery) {
        const map = new Map();
        for (const d of delivery || []) {
            const key = d.project || "—";
            if (!map.has(key)) {
                map.set(key, { project: key, customer: d.customer || "", tasks: [], hours: 0, amount: 0 });
            }
            const g = map.get(key);
            if (!g.customer && d.customer) g.customer = d.customer;
            g.tasks.push(d);
            g.hours += d.hours || 0;
            g.amount += d.amount || 0;
        }
        return [...map.values()];
    }

    toggleProjectGroup(rowId, project, ev, section = "delivery") {
        if (ev) ev.stopPropagation();
        const key = `${rowId}::${section}::${project}`;
        const next = { ...this.state.expandedProjects };
        next[key] = !next[key];
        this.state.expandedProjects = next;
    }

    isProjectExpanded(rowId, project, section = "delivery") {
        return !!this.state.expandedProjects[`${rowId}::${section}::${project}`];
    }

    money(v, currencyId) {
        return formatMonetary(v || 0, { currencyId });
    }

    num(v) {
        return formatFloat(v || 0, { digits: [16, 2] });
    }

    // ── Row selection helper, shared with the Performance Management
    //    Report export below. Strictly the checked rows — nothing else.
    _exportRecords() {
        if (!this.selectedCount) return [];
        return this.visibleLeafRecords().filter((r) => this.state.selected[r.id]);
    }

    // ── Performance Management Report (fixed 3-tab workbook) ─────────────
    // Tab 1 is one row per CHECKED employee-month on the current dashboard
    // (nothing checked = nothing exported); Tab 2 subtotals those same rows
    // per team plus a total; Tab 3 is the full overdue invoice aging list
    // (unrelated to row selection — sourced firm-wide from account.move via
    // get_overdue_invoices).
    async exportPerformanceManagementReport() {
        const TEAM_LABELS = {
            sales: "Sales", audit: "Audit", tax: "Tax",
            accounting: "Accounting", einvoicing: "E-Invoicing", other: "Other",
        };
        const TEAM_ORDER = ["sales", "audit", "tax", "accounting", "einvoicing", "other"];
        const UNCLASSIFIED = "Unclassified";

        const records = this._exportRecords();
        if (!records.length) {
            this.dialog.add(AlertDialog, {
                title: "No records selected",
                body: "Select at least one record to export.",
            });
            return;
        }

        this.state.loading = true;
        let overdue;
        try {
            overdue = await this.orm.call("mis.performance.line", "get_overdue_invoices", []);
        } finally {
            this.state.loading = false;
        }

        // ── Tab 1 — Individual Summary ────────────────────────────────
        const sheet1Columns = [
            { name: "employee_name", label: "Name", type: "char" },
            { name: "team", label: "Team", type: "char" },
            { name: "office_location", label: "Location (UAE/India)", type: "char" },
            { name: "monthly_ctc", label: "Monthly CTC", type: "monetary", agg: true },
            { name: "monthly_obligation", label: "Min. Obligation (AED)", type: "monetary", agg: true },
            { name: "invoices_raised_count", label: "Invoices Raised (No.)", type: "integer", agg: true },
            { name: "invoices_raised_amount", label: "Invoices Raised (AED)", type: "monetary", agg: true },
            { name: "payments_collected_amount", label: "Payments Collected (AED)", type: "monetary", agg: true },
            { name: "work_completed_value", label: "Work Completed – Value (AED)", type: "monetary", agg: true },
            { name: "vs_obligation", label: "vs. Min. Obligation", type: "percent" },
            { name: "status", label: "Status", type: "char" },
        ];

        const sheet1Rows = [];
        const teamTotals = {};
        for (const r of records) {
            const obligation = r.monthly_obligation || 0;
            const completed = r.work_completed_value || 0;
            const teamCode = TEAM_LABELS[r.performance_team] ? r.performance_team : "__unclassified__";

            sheet1Rows.push({
                employee_name: r.employee_name,
                team: TEAM_LABELS[teamCode] || UNCLASSIFIED,
                office_location: r.office_location,
                monthly_ctc: r.monthly_ctc,
                monthly_obligation: obligation,
                invoices_raised_count: r.invoices_raised_count,
                invoices_raised_amount: r.invoices_raised_amount,
                payments_collected_amount: r.payments_collected_amount,
                work_completed_value: completed,
                vs_obligation: obligation > 0 ? (completed / obligation) * 100 : 0,
                // This sheet's "Status" column now reads the real Status
                // field; escalation_stage is blank for compliant employees.
                status: r.performance_status,
            });

            const t = teamTotals[teamCode] || (teamTotals[teamCode] = {
                member_count: 0, monthly_ctc: 0, monthly_obligation: 0,
                invoices_raised_count: 0, invoices_raised_amount: 0,
                payments_collected_amount: 0, work_completed_value: 0,
            });
            t.member_count += 1;
            t.monthly_ctc += r.monthly_ctc || 0;
            t.monthly_obligation += obligation;
            t.invoices_raised_count += r.invoices_raised_count || 0;
            t.invoices_raised_amount += r.invoices_raised_amount || 0;
            t.payments_collected_amount += r.payments_collected_amount || 0;
            t.work_completed_value += completed;
        }
        const sheet1Totals = {};
        for (const col of sheet1Columns) {
            if (col.agg) {
                sheet1Totals[col.name] = sheet1Rows.reduce(
                    (s, r) => s + (Number(r[col.name]) || 0), 0
                );
            }
        }

        // ── Tab 2 — Team Totals (one section per team + firm total) ────
        const sheet2Columns = [
            { name: "team", label: "Team", type: "char" },
            { name: "member_count", label: "Members", type: "integer" },
            { name: "monthly_ctc", label: "Monthly CTC", type: "monetary", agg: true },
            { name: "monthly_obligation", label: "Min. Obligation (AED)", type: "monetary", agg: true },
            { name: "invoices_raised_count", label: "Invoices Raised (No.)", type: "integer", agg: true },
            { name: "invoices_raised_amount", label: "Invoices Raised (AED)", type: "monetary", agg: true },
            { name: "payments_collected_amount", label: "Payments Collected (AED)", type: "monetary", agg: true },
            { name: "work_completed_value", label: "Work Completed – Value (AED)", type: "monetary", agg: true },
            { name: "vs_obligation", label: "vs. Min. Obligation", type: "percent" },
        ];
        const sheet2Rows = [];
        const firmTotal = {
            member_count: 0, monthly_ctc: 0, monthly_obligation: 0,
            invoices_raised_count: 0, invoices_raised_amount: 0,
            payments_collected_amount: 0, work_completed_value: 0,
        };
        const orderIndex = (code) => {
            const i = TEAM_ORDER.indexOf(code);
            return i === -1 ? TEAM_ORDER.length : i;
        };
        for (const code of Object.keys(teamTotals).sort(
            (a, b) => orderIndex(a) - orderIndex(b)
        )) {
            const t = teamTotals[code];
            sheet2Rows.push({
                team: TEAM_LABELS[code] || UNCLASSIFIED,
                ...t,
                vs_obligation: t.monthly_obligation > 0
                    ? (t.work_completed_value / t.monthly_obligation) * 100 : 0,
            });
            for (const k of Object.keys(firmTotal)) firmTotal[k] += t[k];
        }
        sheet2Rows.push({
            team: "Firm Total",
            ...firmTotal,
            vs_obligation: firmTotal.monthly_obligation > 0
                ? (firmTotal.work_completed_value / firmTotal.monthly_obligation) * 100 : 0,
        });

        // ── Tab 3 — Overdue Invoice Detail ──────────────────────────────
        const sheet3Columns = [
            { name: "invoice_no", label: "Invoice No.", type: "char" },
            { name: "client", label: "Client", type: "char" },
            { name: "team", label: "Team", type: "char" },
            { name: "pm_responsible", label: "PM Responsible", type: "char" },
            { name: "invoice_date", label: "Invoice Date", type: "char" },
            { name: "due_date", label: "Due Date", type: "char" },
            { name: "amount_aed", label: "Amount (AED)", type: "monetary", agg: true },
            { name: "days_overdue", label: "Days Overdue", type: "integer" },
            { name: "ar_responsible", label: "AR Responsible", type: "char" },
            { name: "last_follow_up_date", label: "Last Follow-Up Date", type: "char" },
        ];
        const sheet3Totals = {
            amount_aed: overdue.reduce((s, r) => s + (Number(r.amount_aed) || 0), 0),
        };

        const payload = {
            title: "Performance Management Report",
            subtitle: `${this.config.title} — ${records.length} record(s) selected — amounts in AED`,
            sheet1: {
                name: "Individual Summary",
                columns: sheet1Columns,
                rows: sheet1Rows,
                totals: sheet1Totals,
            },
            sheet2: {
                name: "Team Totals",
                columns: sheet2Columns,
                rows: sheet2Rows,
                totals: {},
            },
            sheet3: {
                name: "Overdue Invoice Detail",
                columns: sheet3Columns,
                rows: overdue,
                totals: sheet3Totals,
            },
        };

        let resp;
        try {
            resp = await fetch("/mis_report_kgrn/export/performance_xlsx", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
        } catch (e) {
            console.error("MIS performance management report export failed:", e);
            return;
        }
        if (!resp.ok) {
            console.error("MIS performance management report export failed:", await resp.text());
            return;
        }
        const blob = await resp.blob();
        const filename = `Performance_Management_Report_${new Date().toISOString().slice(0, 10)}.xlsx`;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
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
        if (col.ratio) {
            const [numName, denomName] = col.ratio;
            const denom = Number(rec[denomName]) || 0;
            const value = denom ? ((Number(rec[numName]) || 0) / denom) * 100 : 0;
            return this._format(col, value, this.currencyId(rec, col.currency));
        }
        // a column may pin its own currency field (e.g. CTC in local currency)
        return this._format(col, rec[col.name], this.currencyId(rec, col.currency));
    }

    formatAgg(col, node) {
        if (!col.agg && !col.ratio) return "";
        const cur =
            node.records && node.records.length ? this.currencyId(node.records[0]) : undefined;
        return this._format(col, node.aggregates[col.name], cur);
    }

    formatTotal(col) {
        if (!col.agg && !col.ratio) return "";
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
