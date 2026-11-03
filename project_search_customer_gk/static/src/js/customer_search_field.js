/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { many2OneField, Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

// Keep in step with MIN_SEARCH_CHARS in models/project_search_customer.py.
const MIN_SEARCH_CHARS = 3;
const WIZARD_MODEL = "project.search.customer.wizard";
const PREVIEW_MODEL = "project.search.customer.preview";

/**
 * Customer picker for Project > Search Existing Customer: nothing is listed
 * until MIN_SEARCH_CHARS are typed, matches come from the wizard's
 * search_customers(), and the dropdown never offers Create or Search More.
 */
class ProjectCustomerSearchAutocomplete extends Many2XAutocomplete {
    search(name) {
        return this.orm.call(WIZARD_MODEL, "search_customers", [name], {
            context: this.props.context,
        });
    }

    async loadOptionsSource(request) {
        if (request.trim().length < MIN_SEARCH_CHARS) {
            return [
                {
                    label: _t("Type at least %s characters...", MIN_SEARCH_CHARS),
                    classList: "o_m2o_start_typing",
                    unselectable: true,
                },
            ];
        }
        if (this.lastProm) {
            this.lastProm.abort(false);
        }
        this.lastProm = this.abortableSearch(request);
        const records = await this.lastProm.promise;
        if (!records.length) {
            return [
                {
                    label: _t("No matching customers found."),
                    classList: "o_m2o_no_result",
                    unselectable: true,
                },
            ];
        }
        return records.map((result) => this.mapRecordToOption(result));
    }
}

class ProjectCustomerSearchField extends Many2OneField {
    static components = {
        ...Many2OneField.components,
        Many2XAutocomplete: ProjectCustomerSearchAutocomplete,
    };
}

registry.category("fields").add("project_customer_search", {
    ...many2OneField,
    component: ProjectCustomerSearchField,
    displayName: _t("Project Customer Search"),
});

/**
 * Result list: a row click redirects to the sale order form (the search dialog
 * closes; the breadcrumb leads back to where the user came from).
 *
 * If the server says the user could not open that order (e.g. its company is
 * not selected in the company switcher), a read-only copy built with sudo opens
 * on top of the search dialog instead. The dialog service is used for that
 * rather than doAction, because a second target="new" action would close the
 * search.
 */
class ProjectCustomerOrdersField extends X2ManyField {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.opening = false;
    }

    async openRecord(record) {
        const orderId = record.data.order_id;
        if (!orderId || this.opening) {
            return;
        }
        this.opening = true;
        try {
            const result = await this.orm.call(WIZARD_MODEL, "action_open_order", [orderId], {
                context: this.props.context,
            });
            if (result.type) {
                return await this.action.doAction(result);
            }
            this.dialog.add(FormViewDialog, {
                resModel: PREVIEW_MODEL,
                resId: result.preview_id,
                mode: "readonly",
                preventCreate: true,
                preventEdit: true,
                size: "xl",
                title: record.data.order_name || _t("Quotation"),
            });
        } finally {
            this.opening = false;
        }
    }
}

registry.category("fields").add("project_customer_orders", {
    ...x2ManyField,
    component: ProjectCustomerOrdersField,
    displayName: _t("Customer Orders"),
});
