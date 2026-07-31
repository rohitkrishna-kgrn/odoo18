/** @odoo-module **/

import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

/**
 * A new ticket must never be created except by an explicit click on the
 * Save button. Odoo's default FormController auto-saves a dirty record
 * when the user navigates away, hides/switches the browser tab, or
 * refreshes/closes the page. For a brand-new (unsaved) ticket that would
 * silently create a database record the user never asked to save, so
 * those auto-save hooks are skipped while the record is still new.
 */
class HelpdeskTicketFormController extends FormController {
    async beforeLeave() {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeLeave();
    }

    async beforeUnload(ev) {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeUnload(ev);
    }

    beforeVisibilityChange() {
        if (this.model.root.isNew) {
            return;
        }
        return super.beforeVisibilityChange();
    }
}

registry.category("views").add("helpdesk_ticket_form", {
    ...formView,
    Controller: HelpdeskTicketFormController,
});
