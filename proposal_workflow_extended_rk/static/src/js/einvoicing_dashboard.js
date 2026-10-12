/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const MONTH_MS = 30 * 24 * 60 * 60 * 1000;

function toISO(date) {
    return date.toISOString().slice(0, 10);
}

export class EinvoicingDashboard extends Component {
    static template = "proposal_workflow_extended_rk.EinvoicingDashboard";
    static props = ["*"];
    static components = { Dropdown, DropdownItem };

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
            status_api: false,
            focus: "",
            canExport: false,
            selected: {},
        });

        onWillStart(async () => {
            this.state.canExport = await user.hasGroup("sales_team.group_sale_manager");
            await this.load();
        });
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
            this.state.rows.forEach((r, i) => (r._k = i));
            this.state.selected = {};
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
        this.state.focus = "";
        if (this.clearDates) {
            this.state.dateFrom = "";
            this.state.dateTo = "";
        }
        this.load();
    }

    /** Clicking the Proposals (S) / Agreements (SE) header floats the rows that
     *  have one to the top; a second click, or Refresh, restores the order. */
    toggleFocus(kind) {
        this.state.focus = this.state.focus === kind ? "" : kind;
    }

    get sortedRows() {
        const kind = this.state.focus;
        if (!kind) {
            return this.state.rows;
        }
        const key = kind === "proposals" ? "proposal_count" : "agreement_count";
        const has = this.state.rows.filter((r) => r[key] > 0);
        const rest = this.state.rows.filter((r) => !(r[key] > 0));
        return [...has, ...rest];
    }

    // ── Row selection + Excel export ─────────────────────────────────────
    // Rows are keyed by `_k`, their position when loaded: the table can be
    // re-sorted and the "(No pipeline record)" row has no id.
    get selectedCount() {
        return Object.values(this.state.selected).filter(Boolean).length;
    }

    /** What "select all" covers: with the Proposals (S) / Agreements (SE)
     *  header active, only the rows that have one; otherwise every row. */
    get selectableRows() {
        const kind = this.state.focus;
        if (!kind) {
            return this.state.rows;
        }
        const key = kind === "proposals" ? "proposal_count" : "agreement_count";
        return this.state.rows.filter((r) => r[key] > 0);
    }

    get allSelected() {
        const rows = this.selectableRows;
        return rows.length > 0 && rows.every((r) => this.state.selected[r._k]);
    }

    toggleRow(index) {
        this.state.selected[index] = !this.state.selected[index];
    }

    toggleAll() {
        const on = !this.allSelected;
        this.state.selected = {};
        if (on) {
            this.selectableRows.forEach((r) => (this.state.selected[r._k] = true));
        }
    }

    async exportExcel() {
        const rows = this.state.rows.filter((r) => this.state.selected[r._k]);
        if (!rows.length) {
            this.env.services.notification.add("Select at least one record to export.", {
                type: "warning",
            });
            return;
        }
        const columns = [
            { name: "crm_ref", label: "CRM Ref" },
            { name: "name", label: "Opportunity" },
            { name: "partner", label: "Customer" },
            { name: "stage", label: "Stage" },
            { name: "salesperson", label: "Salesperson" },
            { name: "proposals", label: "Proposals (S)" },
            { name: "proposal_value", label: "Expected Value", type: "number" },
            { name: "agreements", label: "Agreements (SE)" },
            { name: "agreement_value", label: "Order Value", type: "number" },
        ];
        if (this.state.status_api) {
            columns.push(
                { name: "project_status", label: "Project Status" },
                { name: "uat", label: "UAT AR/AP" },
                { name: "live", label: "Live AR/AP" }
            );
        }
        columns.push({ name: "activity", label: "Last Activity" });
        const data = rows.map((row) => ({
            ...row,
            proposals: (row.proposal_names || []).join(", "),
            agreements: (row.agreement_names || []).join(", "),
            project_status: row.status_api && row.status_api.project_status,
            uat: row.status_api && row.status_api.uat && row.status_api.uat.label,
            live: row.status_api && row.status_api.live && row.status_api.live.label,
            activity: this.activityLabel(row),
        }));
        let resp;
        try {
            resp = await fetch("/proposal_workflow_extended_rk/export/dashboard_xlsx", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: this.state.title, columns, rows: data }),
            });
        } catch (e) {
            resp = null;
        }
        if (!resp || !resp.ok) {
            this.env.services.notification.add("The Excel export failed.", { type: "danger" });
            return;
        }
        const link = document.createElement("a");
        link.href = URL.createObjectURL(await resp.blob());
        link.download = `${this.state.title.replace(/\s+/g, "_")}_${toISO(new Date())}.xlsx`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
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
        if (row.is_converted) {
            return "Converted";
        }
        if (row.days_since_activity === false) {
            return "—";
        }
        if (row.days_since_activity === 0) {
            return "Today";
        }
        return `${row.days_since_activity}d ago`;
    }

    /** CSS modifier for the Project Status pill: groups the tracker's
     *  statusCode into the same four buckets used in the API.md ordering. */
    statusCategory(code) {
        if (!code) {
            return "na";
        }
        if (code === "LIVE") {
            return "live";
        }
        if (code.startsWith("IMPL")) {
            return "impl";
        }
        if (code.startsWith("GAP")) {
            return "gap";
        }
        return "not-started";
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
