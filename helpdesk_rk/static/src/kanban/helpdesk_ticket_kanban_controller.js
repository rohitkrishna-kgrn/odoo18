/** @odoo-module **/

import { registry } from "@web/core/registry";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

/**
 * A ticket only becomes visible to the support workflow once it is
 * submitted (Draft -> New). At that point the backend notifies the
 * Helpdesk Support/Admin groups on the bus; every connected agent is
 * already implicitly subscribed to their own group channels, so we just
 * need to react to the notification by reloading the board in place -
 * no manual page refresh required.
 *
 * Stage changes (e.g. New -> In Progress -> Done/Rejected) are pushed the
 * same way, so a ticket's card moves column / updates its badge live for
 * every viewer without a page refresh.
 */
class HelpdeskTicketKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.busService = useService("bus_service");
        this.onTicketCreated = () => ignoreDestroyedComponentError(this.model.load());
        this.busService.subscribe("helpdesk_rk_ticket_created", this.onTicketCreated);
        this.busService.subscribe("helpdesk_rk_ticket_updated", this.onTicketCreated);
        onWillUnmount(() => {
            this.busService.unsubscribe("helpdesk_rk_ticket_created", this.onTicketCreated);
            this.busService.unsubscribe("helpdesk_rk_ticket_updated", this.onTicketCreated);
        });
    }
}

registry.category("views").add("helpdesk_ticket_kanban", {
    ...kanbanView,
    Controller: HelpdeskTicketKanbanController,
});
