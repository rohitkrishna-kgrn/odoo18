/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

export class WhyNotCollectedDialog extends Component {
    static template = "weekly_overdue_invoice_report_gk.WhyNotCollectedDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        invoiceName: String,
        daysOverdue: Number,
        amountDue: Number,
        onSave: Function,
    };

    setup() {
        this.state = useState({ reason: "", saving: false });
    }

    get title() {
        return _t("Why hasn't %(invoice)s been collected?", { invoice: this.props.invoiceName });
    }

    get amountLabel() {
        return this.props.amountDue.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    async onSave() {
        const reason = this.state.reason.trim();
        if (!reason) {
            return;
        }
        this.state.saving = true;
        await this.props.onSave(reason);
        this.state.saving = false;
        this.props.close();
    }

    onRemindLater() {
        this.props.close();
    }
}
