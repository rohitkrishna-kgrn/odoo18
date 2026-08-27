/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useEffect } from "@odoo/owl";
import {
    AccountMoveFormController,
    AccountMoveFormView,
} from "@account/components/account_move_form/account_move_form";
import { WhyNotCollectedDialog } from "./why_not_collected_dialog";

/**
 * On top of everything the stock account.move form already does, pop up a
 * dialog asking "Why Not Collected?" whenever a customer invoice/credit note
 * more than 30 days overdue is opened and needs one — this is the AR owner's
 * (PM's) prompt to fill it in (or refresh it, once 7+ days old) before the
 * Monday overdue report goes out. The condition itself
 * (`why_not_collected_needs_prompt`) is computed server-side. Re-registered
 * under the same "account_move_form" key (force: true) so all of core's own form behavior
 * (print menu, deletion dialog, notebook tab-switch autosave, ...) is
 * preserved; only the popup is added on top via a subclass.
 */
class WeeklyOverdueWhyNotCollectedFormController extends AccountMoveFormController {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        useEffect(
            () => this._maybePromptWhyNotCollected(),
            () => [this.model.root.resId]
        );
    }

    _maybePromptWhyNotCollected() {
        const record = this.model.root;
        if (record.isNew) {
            return;
        }
        const data = record.data;
        if (!data.why_not_collected_needs_prompt) {
            return;
        }
        this.dialogService.add(WhyNotCollectedDialog, {
            invoiceName: data.name || "",
            daysOverdue: data.invoice_age_days,
            amountDue: data.amount_residual || 0,
            onSave: async (reason) => {
                await record.update({ why_not_collected: reason });
                await record.save();
            },
        });
    }
}

registry.category("views").add(
    "account_move_form",
    {
        ...AccountMoveFormView,
        Controller: WeeklyOverdueWhyNotCollectedFormController,
    },
    { force: true }
);
