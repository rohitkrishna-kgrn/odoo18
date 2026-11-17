/** @odoo-module **/
import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { formatDate, deserializeDate } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * E-Invoicing Projects dashboard (data: einvoicing.phase1.project.get_dashboard_data).
 *
 * Every role sees every row (only multi-company rules apply). Every figure opens the rows
 * behind it - the server hands each one its domain.
 *
 * Colours (validated with the dataviz palette checker, light surface):
 *  - one-hue magnitude: blue #2a78d6
 *  - two series (Listed vs Pending): blue #2a78d6 + orange #eb6834, legend + figures
 *  - Emaratax state: status colours, always with an icon and a label
 */
const BLUE = "#2a78d6";
const INK = "#0b0b0b";
const MUTED = "#898781";
const GRID = "#e1e0d9";
const BASELINE = "#c3c2b7";
const FONT = { family: "system-ui, -apple-system, 'Segoe UI', sans-serif", size: 11 };

const EMARATAX_META = {
    active: { icon: "fa-check-circle", cls: "o_epm_st_good" },
    suspended: { icon: "fa-pause-circle", cls: "o_epm_st_warning" },
    delinked: { icon: "fa-chain-broken", cls: "o_epm_st_critical" },
    none: { icon: "fa-circle-o", cls: "o_epm_st_none" },
};

/** Draws each bar's value just past its tip, in text ink (never the bar colour). */
const tipLabels = {
    id: "epmTipLabels",
    afterDatasetsDraw(chart) {
        const { ctx } = chart;
        const horizontal = chart.options.indexAxis === "y";
        ctx.save();
        ctx.font = "600 11px " + FONT.family;
        ctx.fillStyle = INK;
        chart.getDatasetMeta(0).data.forEach((bar, i) => {
            const value = chart.data.datasets[0].data[i];
            if (!value && horizontal === false) {
                return; // empty months stay quiet; the axis already says 0
            }
            if (horizontal) {
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                ctx.fillText(String(value), bar.x + 6, bar.y);
            } else {
                ctx.textAlign = "center";
                ctx.textBaseline = "bottom";
                ctx.fillText(String(value), bar.x, bar.y - 4);
            }
        });
        ctx.restore();
    },
};

export class EinvoicingProjectDashboard extends Component {
    static template = "einvoicing_project_management_rk.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.emarataxMeta = EMARATAX_META;
        this.state = useState({
            data: null,
            error: false,
            loading: false,
            salespersonId: false,
            tables: { progress: false, renewals: false },
        });
        this.charts = [];
        this.progressRef = useRef("progressChart");
        this.renewalsRef = useRef("renewalsChart");

        onWillStart(async () => {
            try {
                // Chart.js ships with Odoo in a lazy bundle.
                await loadBundle("web.chartjs_lib");
            } catch (error) {
                this.state.error = _t("Could not load the chart library: %s", error.message);
            }
            await this.load();
        });
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.data, this.state.tables.progress, this.state.tables.renewals]
        );
    }

    get data() {
        return this.state.data;
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "einvoicing.phase1.project", "get_dashboard_data", [], {
                    salesperson_id: this.state.salespersonId || false,
                }
            );
            this.state.error = false;
        } catch (error) {
            this.state.error = (error.data && error.data.message) || error.message || _t("Could not load the dashboard.");
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------- helpers
    pct(part, whole) {
        return whole ? Math.round((part * 100) / whole) : 0;
    }
    widthStyle(part, whole) {
        const pct = whole ? Math.max((part * 100) / whole, part ? 2 : 0) : 0;
        return "width: " + pct.toFixed(1) + "%";
    }
    growStyle(count) {
        return "flex-grow: " + count;
    }
    /** a segment prints its share only where the text has room */
    segmentLabel(count, total) {
        const pct = this.pct(count, total);
        return pct >= 12 ? pct + "%" : "";
    }
    get maxPerson() {
        return Math.max(1, ...this.data.salespeople.map((p) => p.listed + p.pending));
    }
    get emarataxSegments() {
        return this.data.emaratax.filter((e) => e.count > 0);
    }
    fmtDate(value) {
        return value ? formatDate(deserializeDate(value)) : "";
    }
    renewalWhen(days) {
        if (days < 0) {
            return _t("%s days overdue", -days);
        }
        if (days === 0) {
            return _t("Today");
        }
        return _t("In %s days", days);
    }
    get scopeLabel() {
        return _t("All Phase 1 Projects");
    }

    // ------------------------------------------------------------- actions
    onSalespersonChange(ev) {
        this.state.salespersonId = parseInt(ev.target.value, 10) || false;
        this.load();
    }
    toggleTable(key) {
        this.state.tables[key] = !this.state.tables[key];
    }
    openProjects(title, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "einvoicing.phase1.project",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
            target: "current",
        });
    }
    openProject(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "einvoicing.phase1.project",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
    openPendingList() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Pending"),
            res_model: "einvoicing.phase1.pending",
            views: [[false, "list"], [false, "form"]],
            domain: this.data.domains.pending,
            target: "current",
        });
    }
    openPending(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "einvoicing.phase1.pending",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
    openKpi(key) {
        const d = this.data;
        const titles = {
            total: _t("Phase 1 Projects"),
            ga_done: _t("Gap Assessment Done"),
            uat: _t("UAT Onboarded"),
            emaratax_active: _t("Emaratax Active"),
            live: _t("LIVE Middleware"),
            renew_due: _t("Renewals in 30 Days"),
            renew_overdue: _t("Renewals Overdue"),
        };
        const progress = Object.fromEntries(d.progress.map((p) => [p.key, p.domain]));
        const domains = {
            total: progress.listed,
            ga_done: progress.ga_done,
            uat: progress.uat,
            emaratax_active: progress.emaratax,
            live: progress.live,
            renew_due: d.domains.renew_due,
            renew_overdue: d.domains.renew_overdue,
        };
        this.openProjects(titles[key], domains[key]);
    }

    // -------------------------------------------------------------- charts
    destroyCharts() {
        this.charts.forEach((chart) => chart.destroy());
        this.charts = [];
    }
    baseOptions(onPick) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#ffffff",
                    titleColor: INK,
                    bodyColor: "#52514e",
                    borderColor: GRID,
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    titleFont: { ...FONT, weight: "600", size: 12 },
                    bodyFont: FONT,
                },
            },
            onClick: (event, elements) => {
                if (elements.length) {
                    onPick(elements[0].index);
                }
            },
            onHover: (event, elements) => {
                event.native.target.style.cursor = elements.length ? "pointer" : "default";
            },
        };
    }
    renderCharts() {
        this.destroyCharts();
        const d = this.data;
        if (!d || !window.Chart) {
            return;
        }
        const Chart = window.Chart;

        // Onboarding progress: one hue, horizontal, value at the tip.
        if (this.progressRef.el && !this.state.tables.progress) {
            const options = this.baseOptions((i) => this.openProjects(d.progress[i].label, d.progress[i].domain));
            options.indexAxis = "y";
            options.layout = { padding: { right: 28 } };
            options.scales = {
                x: {
                    beginAtZero: true,
                    suggestedMax: Math.max(1, d.kpis.total),
                    ticks: { precision: 0, color: MUTED, font: FONT },
                    grid: { color: GRID, lineWidth: 1 },
                    border: { display: false },
                },
                y: {
                    ticks: { color: "#52514e", font: { ...FONT, size: 12 } },
                    grid: { display: false },
                    border: { color: BASELINE },
                },
            };
            options.plugins.tooltip.callbacks = {
                label: (ctx) => _t("%(count)s of %(total)s TRNs (%(pct)s%)", {
                    count: ctx.raw, total: d.kpis.total, pct: this.pct(ctx.raw, d.kpis.total),
                }),
            };
            this.charts.push(new Chart(this.progressRef.el, {
                type: "bar",
                data: {
                    labels: d.progress.map((p) => p.label),
                    datasets: [{
                        data: d.progress.map((p) => p.count),
                        backgroundColor: BLUE,
                        hoverBackgroundColor: "#1c5cab",
                        barThickness: 22,
                        borderRadius: 4,
                        borderSkipped: "start",
                    }],
                },
                options,
                plugins: [tipLabels],
            }));
        }

        // Renewals by month: one hue, columns, value on the cap.
        if (this.renewalsRef.el && !this.state.tables.renewals) {
            const months = d.renewal_months;
            const options = this.baseOptions((i) => this.openProjects(
                _t("Renewals - %s", months[i].label), months[i].domain));
            options.layout = { padding: { top: 18 } };
            options.scales = {
                x: {
                    ticks: { color: MUTED, font: FONT, maxRotation: 0, autoSkip: true },
                    grid: { display: false },
                    border: { color: BASELINE },
                },
                y: {
                    beginAtZero: true,
                    suggestedMax: 1,
                    ticks: { precision: 0, color: MUTED, font: FONT },
                    grid: { color: GRID, lineWidth: 1 },
                    border: { display: false },
                },
            };
            options.plugins.tooltip.callbacks = {
                title: (items) => months[items[0].dataIndex].label,
                label: (ctx) => _t("%s renewals", ctx.raw),
            };
            this.charts.push(new Chart(this.renewalsRef.el, {
                type: "bar",
                data: {
                    labels: months.map((m) => m.short),
                    datasets: [{
                        data: months.map((m) => m.count),
                        backgroundColor: BLUE,
                        hoverBackgroundColor: "#1c5cab",
                        maxBarThickness: 24,
                        borderRadius: 4,
                        borderSkipped: "start",
                    }],
                },
                options,
                plugins: [tipLabels],
            }));
        }
    }
}

registry.category("actions").add("einvoicing_pm.dashboard", EinvoicingProjectDashboard);
