/** @odoo-module **/
import { Component, onWillStart, onMounted, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { formatDate, deserializeDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";

/**
 * Employee Documents dashboard (data: models/dashboard.py).
 * HR / Administrator: every employee with a login, whether they submitted their personal details
 * and documents per category, and how far those got. Employees: the same for themselves only.
 * The page reloads itself on "hr_dms/changed" (live_refresh.js).
 * Laid out like the eInvoicing dashboards (KGRN navy/orange, Chart.js cards).
 */
const NAVY = "#1A2F4E";
// status colours, matching the pills in dashboard.scss
const STATE_COLORS = {
    not_started: "#D0D5DD",
    draft: "#98A2B3",
    submitted: "#F79009",
    approved: "#12B76A",
    verified: "#12B76A",
    rejected: "#D92D20",
};
const CHART_FONT = { family: "Inter, sans-serif", size: 11 };
const DOC_STATES = [
    { key: "draft", label: _t("Draft"), icon: "fa-pencil" },
    { key: "submitted", label: _t("Submitted"), icon: "fa-hourglass-half" },
    { key: "approved", label: _t("Approved"), icon: "fa-check" },
    { key: "rejected", label: _t("Rejected"), icon: "fa-times" },
];
const DETAILS_STATES = [
    { key: "not_started", label: _t("Not started"), icon: "fa-circle-o" },
    { key: "draft", label: _t("Draft"), icon: "fa-pencil" },
    { key: "submitted", label: _t("Submitted"), icon: "fa-hourglass-half" },
    { key: "verified", label: _t("Verified"), icon: "fa-check" },
];
const FILTERS = [
    { key: "all", label: _t("All") },
    { key: "details_open", label: _t("Personal details not submitted") },
    { key: "pending", label: _t("Documents pending") },
    { key: "rejected", label: _t("Documents rejected") },
    { key: "no_docs", label: _t("No documents") },
];

export class HrDmsDashboard extends Component {
    static template = "hr_dms.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.bus = useService("bus_service");
        this.docStates = DOC_STATES;
        this.detailsStates = DETAILS_STATES;
        this.filters = FILTERS;
        this.state = useState({ data: null, error: false, search: "", department: "", filter: "all", version: 0 });
        this.charts = [];
        this.refs = {
            status: useRef("statusChart"),
            month: useRef("monthChart"),
            category: useRef("categoryChart"),
        };
        this.reload = debounce(() => this.load(), 500);
        onWillStart(async () => {
            try {
                // Chart.js ships with Odoo but lives in a lazy bundle.
                await loadBundle("web.chartjs_lib");
            } catch (error) {
                this.state.error = _t("Could not load the chart library: %s", error.message);
            }
            await this.load();
        });
        // runs after the DOM patch, so the t-ref canvases exist
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.version]
        );
        onMounted(() => {
            this.bus.subscribe("hr_dms/changed", this.reload);
            this.bus.start();
        });
        onWillUnmount(() => {
            this.reload.cancel();
            this.bus.unsubscribe("hr_dms/changed", this.reload);
            this.destroyCharts();
        });
    }

    async load() {
        this.state.data = await this.orm.call("hr.dms.dashboard", "get_dashboard_data", []);
        this.state.version++;
    }

    // ------------------------------------------------------------------ figures
    get data() {
        return this.state.data;
    }
    get me() {
        return this.data.employees[0];
    }
    get employeeCount() {
        return this.data.employees.length;
    }
    get detailsDone() {
        const s = this.data.details_states;
        return s.submitted + s.verified;
    }
    get departments() {
        return [...new Set(this.data.employees.map((e) => e.department).filter(Boolean))].sort();
    }
    get rows() {
        const search = this.state.search.trim().toLowerCase();
        return this.data.employees.filter((e) => {
            if (search && !e.name.toLowerCase().includes(search)) {
                return false;
            }
            if (this.state.department && e.department !== this.state.department) {
                return false;
            }
            switch (this.state.filter) {
                case "details_open":
                    return ["not_started", "draft"].includes(e.details_state);
                case "pending":
                    return e.totals.submitted > 0;
                case "rejected":
                    return e.totals.rejected > 0;
                case "no_docs":
                    return e.doc_count === 0;
            }
            return true;
        });
    }
    get myCategories() {
        // an employee only gets the categories they can see; show where they stand in each
        return this.data.categories.map((cat) => ({ ...cat, cell: this.me?.cells[cat.id] }));
    }
    get categoryChartHeight() {
        return Math.max(160, this.data.categories.length * 34 + 50);
    }
    sum(counts) {
        return Object.values(counts).reduce((a, b) => a + b, 0);
    }
    pct(part, whole) {
        return whole ? Math.round((part / whole) * 100) : 0;
    }
    detailsLabel(key) {
        return DETAILS_STATES.find((s) => s.key === key);
    }
    docState(key) {
        return DOC_STATES.find((s) => s.key === key);
    }
    lastUpload(row) {
        return row.last_upload ? formatDate(deserializeDate(row.last_upload)) : "—";
    }
    cellTitle(row, cat) {
        const cell = row.cells[cat.id];
        if (!cell) {
            return `${cat.name}: ${_t("not submitted")}`;
        }
        const parts = DOC_STATES.filter((s) => cell.counts[s.key]).map((s) => `${cell.counts[s.key]} ${s.label}`);
        return `${cat.name}: ${parts.join(", ")}`;
    }

    setFilter(key) {
        this.state.filter = key;
    }

    // ------------------------------------------------------------------ charts
    destroyCharts() {
        this.charts.forEach((chart) => chart.destroy());
        this.charts = [];
    }
    build(ref, config) {
        if (ref.el) {
            this.charts.push(new window.Chart(ref.el, config));
        }
    }
    renderCharts() {
        this.destroyCharts();
        if (!this.data || !window.Chart) {
            return;
        }
        const d = this.data;
        const legend = { position: "bottom", labels: { font: CHART_FONT, boxWidth: 12 } };

        // HR: personal details forms; employee: their own documents
        const slices = d.is_hr
            ? DETAILS_STATES.map((s) => ({ ...s, value: d.details_states[s.key] }))
            : DOC_STATES.map((s) => ({ ...s, value: d.doc_states[s.key] }));
        this.build(this.refs.status, {
            type: "doughnut",
            data: {
                labels: slices.map((s) => s.label),
                datasets: [{
                    data: slices.map((s) => s.value),
                    backgroundColor: slices.map((s) => STATE_COLORS[s.key]),
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "62%",
                plugins: { legend },
                onClick: (ev, elements) => {
                    if (!elements.length) {
                        return;
                    }
                    if (d.is_hr) {
                        this.openDetailsList();
                    } else {
                        this.openState(slices[elements[0].index].key);
                    }
                },
            },
        });

        this.build(this.refs.month, {
            type: "bar",
            data: {
                labels: d.months.map((m) => m.label),
                datasets: [{ label: _t("Uploaded"), data: d.months.map((m) => m.count), backgroundColor: NAVY, borderRadius: 4 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
            },
        });

        this.build(this.refs.category, {
            type: "bar",
            data: {
                labels: d.categories.map((c) => c.name),
                datasets: DOC_STATES.map((s) => ({
                    label: s.label,
                    data: d.categories.map((c) => c.counts[s.key]),
                    backgroundColor: STATE_COLORS[s.key],
                    borderRadius: 3,
                    maxBarThickness: 22,
                })),
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: "y",
                plugins: { legend: { ...legend, position: "top", align: "end" } },
                scales: {
                    x: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
                    y: { stacked: true, ticks: { font: CHART_FONT } },
                },
                onClick: (ev, elements) => {
                    if (elements.length) {
                        const { index, datasetIndex } = elements[0];
                        this.openCategory(d.categories[index], DOC_STATES[datasetIndex].key);
                    }
                },
                onHover: (ev, elements) => {
                    ev.native.target.style.cursor = elements.length ? "pointer" : "default";
                },
            },
        });
    }

    // ------------------------------------------------------------------ navigation
    openDocuments(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "hr.dms.document",
            views: [[false, "list"], [false, "form"]],
            domain,
            context: { search_default_group_category: this.data.is_hr ? 0 : 1 },
        });
    }
    openState(state) {
        this.openDocuments(this.docState(state).label, [["state", "=", state], ...this.ownDomain()]);
    }
    ownDomain() {
        return this.data.is_hr ? [] : [["employee_id", "=", this.data.employee_id]];
    }
    openExpiring() {
        const limit = new Date();
        limit.setDate(limit.getDate() + 30);
        this.openDocuments(_t("Expiring within 30 days"), [
            ["expiry_date", "!=", false],
            ["expiry_date", "<=", limit.toISOString().slice(0, 10)],
            ...this.ownDomain(),
        ]);
    }
    openEmployee(row) {
        this.openDocuments(row.name, [["employee_id", "=", row.id]]);
    }
    openCell(row, cat) {
        this.openDocuments(`${row.name} · ${cat.name}`, [["employee_id", "=", row.id], ["category_id", "=", cat.id]]);
    }
    openCategory(cat, state = false) {
        const domain = [["category_id", "=", cat.id], ...this.ownDomain()];
        if (state) {
            domain.push(["state", "=", state]);
        }
        this.openDocuments(state ? `${cat.name} · ${this.docState(state).label}` : cat.name, domain);
    }
    openDetails(row) {
        if (row.details_id) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "hr.dms.personal.details",
                res_id: row.details_id,
                views: [[false, "form"]],
            });
        }
    }
    openDetailsList() {
        this.action.doAction("hr_dms.action_hr_dms_details");
    }
    async openMyDetails() {
        const action = await this.orm.call("hr.dms.personal.details", "action_open_my_details", []);
        this.action.doAction(action);
    }
    openMyDocuments() {
        this.action.doAction("hr_dms.action_hr_dms_my_documents");
    }
}

registry.category("actions").add("hr_dms_dashboard", HrDmsDashboard);
