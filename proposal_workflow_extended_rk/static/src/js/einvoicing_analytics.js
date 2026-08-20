/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTH_MS = 30 * 24 * 60 * 60 * 1000;

const NAVY = "#1A2F4E";
const ORANGE = "#F15C22";
// Categorical ramp built around the KGRN brand pair.
const PALETTE = [
    "#F15C22", "#1A2F4E", "#0EA5E9", "#7C3AED", "#12B76A",
    "#F79009", "#D92D20", "#0891B2", "#9333EA", "#65A30D",
];

function toISO(date) {
    return date.toISOString().slice(0, 10);
}

function monthLabel(key) {
    const [year, month] = key.split("-");
    const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${names[parseInt(month, 10) - 1]} ${year.slice(2)}`;
}

export class EinvoicingAnalytics extends Component {
    static template = "proposal_workflow_extended_rk.EinvoicingAnalytics";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.charts = [];

        this.refs = {
            stage: useRef("stageChart"),
            service: useRef("serviceChart"),
            salesperson: useRef("salespersonChart"),
            trend: useRef("trendChart"),
            funnel: useRef("funnelChart"),
            activity: useRef("activityChart"),
        };

        const params = (this.props.action && this.props.action.params) || {};
        this.scope = params.scope || "einvoicing";

        const today = new Date();
        this.state = useState({
            title: params.title || "eInvoicing Analytics",
            subtitle: params.subtitle || "",
            loading: true,
            error: false,
            dateFrom: toISO(new Date(today.getTime() - 12 * MONTH_MS)),
            dateTo: toISO(today),
            salespersonId: "",
            salespersons: [],
            currency: "",
            hasData: false,
            // bumped after every successful load so the effect below re-runs
            version: 0,
        });

        onWillStart(async () => {
            try {
                // Chart.js ships with Odoo but lives in a lazy bundle.
                await loadBundle("web.chartjs_lib");
            } catch (error) {
                this.state.error = `Could not load the chart library: ${error.message}`;
                this.state.loading = false;
                return;
            }
            await this.load();
        });

        // Runs after the DOM patch, so t-ref canvases exist. Awaiting a
        // microtask instead is not enough — OWL renders asynchronously.
        useEffect(
            () => {
                this.renderCharts();
                return () => this.destroyCharts();
            },
            () => [this.state.version]
        );

        onWillUnmount(() => this.destroyCharts());
    }

    destroyCharts() {
        this.charts.forEach((chart) => chart.destroy());
        this.charts = [];
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "einvoicing.dashboard",
                "get_chart_data",
                [],
                {
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    salesperson_id: this.state.salespersonId || false,
                    scope: this.scope,
                }
            );
            this.data = data;
            this.state.salespersons = data.salespersons;
            this.state.currency = data.currency;
            this.state.hasData = data.funnel.values[0] > 0;
            this.state.loading = false;
            this.state.version++;
        } catch (error) {
            this.state.error = error.data ? error.data.message : error.message;
            this.state.loading = false;
        }
    }

    money(value) {
        return `${this.state.currency} ${(value || 0).toLocaleString("en-US", {
            maximumFractionDigits: 0,
        })}`;
    }

    get baseOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { font: { family: "Inter, sans-serif", size: 11 } } },
            },
        };
    }

    /** Money-formatted tooltip shared by the value charts. */
    moneyTooltip() {
        const money = (v) => this.money(v);
        return {
            callbacks: {
                label(context) {
                    const value = context.parsed.y ?? context.parsed.x ?? context.parsed;
                    return ` ${context.label}: ${money(value)}`;
                },
            },
        };
    }

    build(ref, config) {
        if (!ref.el) {
            return;
        }
        this.charts.push(new window.Chart(ref.el, config));
    }

    renderCharts() {
        this.destroyCharts();
        if (!this.state.hasData || !this.data || !window.Chart) {
            return;
        }
        const d = this.data;

        // Pipeline by stage — count as bars, value as a line on a second axis
        this.build(this.refs.stage, {
            type: "bar",
            data: {
                labels: d.stage.labels,
                datasets: [
                    {
                        label: "Records",
                        data: d.stage.counts,
                        backgroundColor: NAVY,
                        borderRadius: 4,
                        yAxisID: "y",
                        order: 2,
                    },
                    {
                        label: "Expected Value",
                        data: d.stage.values,
                        type: "line",
                        borderColor: ORANGE,
                        backgroundColor: ORANGE,
                        borderWidth: 2,
                        tension: 0.3,
                        yAxisID: "y1",
                        order: 1,
                    },
                ],
            },
            options: {
                ...this.baseOptions,
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Records" } },
                    y1: {
                        beginAtZero: true,
                        position: "right",
                        grid: { drawOnChartArea: false },
                        title: { display: true, text: "Value" },
                    },
                },
            },
        });

        // Revenue mix by service — pie
        this.build(this.refs.service, {
            type: "pie",
            data: {
                labels: d.service.labels,
                datasets: [{ data: d.service.values, backgroundColor: PALETTE }],
            },
            options: {
                ...this.baseOptions,
                plugins: {
                    ...this.baseOptions.plugins,
                    legend: { position: "right", labels: { font: { size: 11 } } },
                    tooltip: this.moneyTooltip(),
                },
            },
        });

        // Order value by salesperson — horizontal bars
        this.build(this.refs.salesperson, {
            type: "bar",
            data: {
                labels: d.salesperson.labels,
                datasets: [{
                    label: "Order Value",
                    data: d.salesperson.values,
                    backgroundColor: ORANGE,
                    borderRadius: 4,
                }],
            },
            options: {
                ...this.baseOptions,
                indexAxis: "y",
                plugins: {
                    legend: { display: false },
                    tooltip: this.moneyTooltip(),
                },
                scales: { x: { beginAtZero: true } },
            },
        });

        // Monthly trend — new records against booked order value
        this.build(this.refs.trend, {
            type: "bar",
            data: {
                labels: d.trend.labels.map(monthLabel),
                datasets: [
                    {
                        label: "Order Value",
                        data: d.trend.values,
                        backgroundColor: "rgba(26, 47, 78, .85)",
                        borderRadius: 4,
                        yAxisID: "y",
                    },
                    {
                        label: "New Pipeline Records",
                        data: d.trend.leads,
                        type: "line",
                        borderColor: ORANGE,
                        backgroundColor: ORANGE,
                        borderWidth: 2,
                        tension: 0.3,
                        yAxisID: "y1",
                    },
                ],
            },
            options: {
                ...this.baseOptions,
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: "Value" } },
                    y1: {
                        beginAtZero: true,
                        position: "right",
                        grid: { drawOnChartArea: false },
                        ticks: { precision: 0 },
                        title: { display: true, text: "Records" },
                    },
                },
            },
        });

        // Workflow funnel
        this.build(this.refs.funnel, {
            type: "bar",
            data: {
                labels: d.funnel.labels,
                datasets: [{
                    label: "Records",
                    data: d.funnel.values,
                    backgroundColor: [NAVY, "#2E4A73", "#0EA5E9", "#7C3AED", "#12B76A"],
                    borderRadius: 4,
                }],
            },
            options: {
                ...this.baseOptions,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { precision: 0 } } },
            },
        });

        // Activity health — doughnut
        this.build(this.refs.activity, {
            type: "doughnut",
            data: {
                labels: d.activity.labels,
                datasets: [{
                    data: d.activity.values,
                    backgroundColor: ["#12B76A", "#D92D20"],
                }],
            },
            options: {
                ...this.baseOptions,
                cutout: "62%",
                plugins: {
                    ...this.baseOptions.plugins,
                    legend: { position: "bottom" },
                },
            },
        });
    }

    setRange(months) {
        const today = new Date();
        this.state.dateTo = toISO(today);
        this.state.dateFrom = toISO(new Date(today.getTime() - months * MONTH_MS));
        this.load();
    }
}

registry.category("actions").add("einvoicing_analytics", EinvoicingAnalytics);
