/** @odoo-module **/

import { registry } from "@web/core/registry";
import {
    BooleanFavoriteField,
    booleanFavoriteField,
} from "@web/views/fields/boolean_favorite/boolean_favorite_field";

/**
 * Same star widget used everywhere else (kanban, list), but the autosave
 * behavior always follows whether the ticket already exists in the
 * database instead of a static option:
 *  - Existing ticket: toggling the star saves immediately, exactly like
 *    kanban/list - no need to click the form's main Save button.
 *  - Brand-new/unsaved ticket: toggling the star only updates it in
 *    memory - only the explicit Save button may create the record.
 */
export class HelpdeskTicketFavoriteField extends BooleanFavoriteField {
    async update() {
        if (this.props.readonly) {
            return;
        }
        const changes = { [this.props.name]: !this.props.record.data[this.props.name] };
        await this.props.record.update(changes, { save: !this.props.record.isNew });
    }
}

export const helpdeskTicketFavoriteField = {
    ...booleanFavoriteField,
    component: HelpdeskTicketFavoriteField,
};

registry.category("fields").add("helpdesk_ticket_favorite", helpdeskTicketFavoriteField);
