/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";

const SEARCH_ACTION = "project_search_customer_gk.action_project_search_customer";

/**
 * "Back to Search" on a sale order opened from Project > Search Existing
 * Customer. action_open_order puts the searched customer in the action
 * context as psc_back_partner_id; any other way of opening an order has no
 * such key, so the button never shows there.
 */
patch(FormController.prototype, {
    setup() {
        super.setup(...arguments);
        const ctx = this.props.context || {};
        this.pscBackPartnerId =
            this.props.resModel === "sale.order" && !this.env.inDialog
                ? ctx.psc_back_partner_id || false
                : false;
        if (this.pscBackPartnerId) {
            this.pscActionService = useService("action");
        }
    },

    async onPscBackToSearch() {
        const partnerId = this.pscBackPartnerId;
        const action = this.pscActionService;
        // Back to the page the search was opened from (e.g. Projects). When
        // the order is the only entry in the breadcrumb there is nothing to
        // go back to, so the search simply opens on top of it.
        try {
            await action.restore();
        } catch {
            // No previous page.
        }
        await action.doAction(SEARCH_ACTION, {
            additionalContext: { default_partner_id: partnerId },
        });
    },
});
