/** @odoo-module */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";
import { download } from "@web/core/network/download";
const { Component } = owl;

export class OutstandingPartnerLedger extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const defaults = this._defaultDates();
        this.state = useState({
            partners: [],
            search: "",
            page: 1,
            pages: 1,
            total: 0,
            selected: null,
            date_from: defaults.date_from,
            date_to: defaults.date_to,
            data: null,
            loading: false,
            settings: null,
        });
        this.loadPartners();
    }

    _defaultDates() {
        const today = new Date();
        const y = today.getFullYear();
        const pad = (n) => (n < 10 ? "0" + n : "" + n);
        return {
            date_from: `${y}-01-01`,
            date_to: `${y}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`,
        };
    }

    fmt(n) {
        return (parseFloat(n) || 0).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    async loadPartners() {
        const res = await this.orm.call(
            "account.ledger.extended.rk", "search_partners",
            [this.state.search, this.state.page]);
        this.state.partners = res.partners;
        this.state.page = res.page;
        this.state.pages = res.pages;
        this.state.total = res.total;
    }

    async onSearchInput(ev) {
        this.state.search = ev.target.value;
        this.state.page = 1;
        await this.loadPartners();
    }

    async nextPage() {
        if (this.state.page < this.state.pages) {
            this.state.page += 1;
            await this.loadPartners();
        }
    }

    async prevPage() {
        if (this.state.page > 1) {
            this.state.page -= 1;
            await this.loadPartners();
        }
    }

    async selectPartner(partner) {
        this.state.selected = partner;
        await Promise.all([this.loadLedger(), this.loadSettings()]);
    }

    async loadSettings() {
        this.state.settings = await this.orm.call(
            "account.ledger.extended.rk", "get_partner_settings",
            [this.state.selected.id]);
    }

    async verifyPartner() {
        this.state.settings = await this.orm.call(
            "account.ledger.extended.rk", "verify_partner",
            [this.state.selected.id]);
    }

    async unverifyPartner() {
        this.state.settings = await this.orm.call(
            "account.ledger.extended.rk", "unverify_partner",
            [this.state.selected.id]);
    }

    async toggleEmail() {
        this.state.settings = await this.orm.call(
            "account.ledger.extended.rk", "set_partner_email_enabled",
            [this.state.selected.id, !this.state.settings.email_enabled]);
    }

    async sendEmailNow() {
        const res = await this.orm.call(
            "account.ledger.extended.rk", "send_outstanding_email_now",
            [this.state.selected.id]);
        this.notification.add(res.message, {
            type: res.sent ? "success" : "warning",
        });
    }

    backToList() {
        this.state.selected = null;
        this.state.data = null;
        this.state.settings = null;
    }

    async onDateChange(ev) {
        this.state[ev.target.name] = ev.target.value;
        if (this.state.selected) {
            await this.loadLedger();
        }
    }

    async loadLedger() {
        if (!this.state.selected) {
            return;
        }
        this.state.loading = true;
        this.state.data = await this.orm.call(
            "account.ledger.extended.rk", "get_outstanding_ledger",
            [this.state.selected.id, this.state.date_from, this.state.date_to]);
        this.state.loading = false;
    }

    _reportData() {
        return {
            report_type: "outstanding",
            partner_id: this.state.selected.id,
            date_from: this.state.date_from,
            date_to: this.state.date_to,
        };
    }

    async printPdf() {
        await this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: "accounting_ledger_extended_rk.report_outstanding_ledger",
            report_file: "accounting_ledger_extended_rk.report_outstanding_ledger",
            data: this._reportData(),
            display_name: "Outstanding Ledger",
        });
    }

    async printXlsx() {
        await download({
            url: "/ledger_xlsx_report",
            data: {
                model: "account.ledger.extended.rk",
                data: JSON.stringify(this._reportData()),
                report_name: "Outstanding Ledger - " + this.state.selected.name,
            },
        });
    }

    openInvoice(moveId) {
        if (!moveId) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: moveId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
OutstandingPartnerLedger.template = "accounting_ledger_extended_rk.OutstandingPartnerLedger";
registry.category("actions").add("rk_outstanding_ledger", OutstandingPartnerLedger);
