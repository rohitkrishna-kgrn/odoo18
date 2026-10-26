/** @odoo-module **/

/* Quotation > Entities: the Entity Name cell.
 *
 * One cell that takes either a name typed by hand or an entity picked from the
 * client's eInvoicing discovery form. Picking links the row
 * (`discovery_entity_id`), which fills the name and both annual counts
 * server-side; typing only sets the name, and sale.order.entity.write() drops a
 * link the new name no longer matches.
 *
 * The suggestions are the order's `available_discovery_entity_ids` - the form's
 * entities that no other row has claimed yet. With none left (or no form at
 * all) the dropdown stays shut and the cell is a plain text box, which is what
 * the old pick-only column could not do: it answered "No records" and left the
 * row unnameable.
 */

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { AutoComplete } from "@web/core/autocomplete/autocomplete";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { charField } from "@web/views/fields/char/char_field";
import { useInputField } from "@web/views/fields/input_field_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component } from "@odoo/owl";

export class EntityNameField extends Component {
    static template = "crm_extended_rk.EntityNameField";
    static components = { AutoComplete };
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.inputRef = useChildRef();
        useInputField({
            getValue: () => this.value,
            parse: (value) => value.trim(),
            ref: this.inputRef,
        });
    }

    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    get availableIds() {
        const parent = this.props.record.evalContext.parent;
        return (parent && parent.available_discovery_entity_ids) || [];
    }

    get sources() {
        return [{ options: (request) => this.loadOptions(request) }];
    }

    async loadOptions(request) {
        const ids = this.availableIds;
        if (!ids.length) {
            return [];
        }
        const found = await this.orm.call("crm.lead.discovery.entity", "name_search", [], {
            name: request,
            args: [["id", "in", ids]],
            limit: 8,
        });
        const options = found.map(([id, name]) => ({ id, label: name, entityId: id }));
        // A typed name the form does not have stays one keystroke away: listed
        // first, so Enter keeps what was typed instead of swapping it for the
        // closest form entity.
        const typed = request.trim();
        const norm = (text) => text.toLowerCase().replace(/\s+/g, " ").trim();
        if (typed && !found.some(([, name]) => norm(name) === norm(typed))) {
            options.unshift({ label: _t('Use "%s"', typed), typedName: typed });
        }
        return options;
    }

    async onSelect(option) {
        if (option.entityId) {
            await this.props.record.update({
                [this.props.name]: option.label,
                discovery_entity_id: [option.entityId, option.label],
            });
        } else if (option.typedName !== this.value) {
            await this.props.record.update({ [this.props.name]: option.typedName });
        }
    }
}

export const entityNameField = {
    ...charField,
    component: EntityNameField,
    extractProps: ({ attrs }) => ({ placeholder: attrs.placeholder }),
};

registry.category("fields").add("discovery_entity_name", entityNameField);
