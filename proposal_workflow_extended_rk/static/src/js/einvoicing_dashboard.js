/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MONTH_MS = 30 * 24 * 60 * 60 * 1000;

function toISO(date) {
    return date.toISOString().slice(0, 10);
}

export class EinvoicingDashboard extends Component {
    static template = "proposal_workflow_extended_rk.EinvoicingDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        // One component, two dashboards: the client action carries the scope
        // and the wording in its params.
        const params = (this.props.action && this.props.action.params) || {};
        this.scope = params.scope || "einvoicing";

        // Some dashboards are meant to open on everything rather than on a
        // rolling window. Where that is set the date boxes start empty and
        // Refresh empties them again, so the button always returns the full
        // picture instead of silently re-applying a range nobody chose.
        this.clearDates = Boolean(params.clear_dates);

        const today = new Date();
        this.state = useState({
            title: params.title || "eInvoicing Dashboard",
            subtitle: params.subtitle || "",
            loading: true,
            error: false,
            dateFrom: this.clearDates ? "" : toISO(new Date(today.getTime() - 3 * MONTH_MS)),
            dateTo: this.clearDates ? "" : toISO(today),
            salespersonId: "",
            rows: [],
            kpis: {},
            salespersons: [],
            currency: "",
            staleDays: 7,
        });

        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "einvoicing.dashboard",
                "get_dashboard_data",
                [],
                {
                    date_from: this.state.dateFrom || false,
                    date_to: this.state.dateTo || false,
                    salesperson_id: this.state.salespersonId || false,
                    scope: this.scope,
                }
            );
            Object.assign(this.state, data);
            this.state.staleDays = data.stale_days;
        } catch (error) {
            this.state.error = error.data ? error.data.message : error.message;
        } finally {
            this.state.loading = false;
        }
    }

    /** Refresh re-reads the data, and on an unfiltered dashboard clears the
     *  dates on the way — the quick ranges are there when a window is wanted. */
    refresh() {
        if (this.clearDates) {
            this.state.dateFrom = "";
            this.state.dateTo = "";
        }
        this.load();
    }

    /** Quick ranges keep the common cases one click away. */
    setRange(months) {
        const today = new Date();
        this.state.dateTo = toISO(today);
        this.state.dateFrom = toISO(new Date(today.getTime() - months * MONTH_MS));
        this.load();
    }

    formatMoney(value) {
        const amount = (value || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        return `${this.state.currency} ${amount}`;
    }

    activityLabel(row) {
        if (row.days_since_activity === false) {
            return "—";
        }
        if (row.days_since_activity === 0) {
            return "Today";
        }
        return `${row.days_since_activity}d ago`;
    }

    openLead(row) {
        // The "(No pipeline record)" row aggregates orders with no lead behind
        // them, so there is nothing to open — its order links still work.
        if (!row.id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Open the orders behind one side of a pipeline record.
     *
     *  Titles are built here rather than in the template: OWL re-compiles a
     *  `${...}` interpolation with a fresh expression compiler that has no
     *  access to the enclosing t-foreach scope, so a template literal naming
     *  the loop variable resolves to undefined at click time.
     */
    openRecordOrders(row, side, ev) {
        const proposals = side === "proposals";
        const label = proposals ? "Proposals" : "Agreements";
        this.openOrderList(
            row.crm_ref ? `${label} — ${row.crm_ref}` : label,
            proposals ? row.proposal_ids : row.agreement_ids,
            ev
        );
    }

    /** Open one side of the split — the Sxxxxx proposals or the SExxxxx
     *  agreements — from either the record table or the service table. */
    openOrderList(title, ids, ev) {
        ev.stopPropagation();
        if (!ids.length) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: title,
            res_model: "sale.order",
            domain: [["id", "in", ids]],
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }
}

registry.category("actions").add("einvoicing_dashboard", EinvoicingDashboard);
