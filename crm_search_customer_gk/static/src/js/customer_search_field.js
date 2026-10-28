/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { many2OneField, Many2OneField } from "@web/views/fields/many2one/many2one_field";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

// Keep in step with MIN_SEARCH_CHARS in models/crm_search_custom.py.
const MIN_SEARCH_CHARS = 3;

/**
 * Customer picker for CRM > Search Customer: nothing is listed until
 * MIN_SEARCH_CHARS are typed, matches come from the wizard's
 * search_customers(), and the dropdown never offers Create or Search More.
 */
class CustomerSearchAutocomplete extends Many2XAutocomplete {
    search(name) {
        return this.orm.call("crm.search.custom.wizard", "search_customers", [name], {
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

class CustomerSearchField extends Many2OneField {
    static components = {
        ...Many2OneField.components,
        Many2XAutocomplete: CustomerSearchAutocomplete,
    };
}

registry.category("fields").add("crm_customer_search", {
    ...many2OneField,
    component: CustomerSearchField,
    displayName: _t("Customer Search"),
});
