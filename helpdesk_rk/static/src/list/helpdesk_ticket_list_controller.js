/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

/**
 * Same live-refresh behavior as the kanban board: reload the list in
 * place when a ticket is submitted and becomes visible to support, so it
 * shows up without a manual page refresh.
 */
class HelpdeskTicketListController extends ListController {
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

registry.category("views").add("helpdesk_ticket_list", {
    ...listView,
    Controller: HelpdeskTicketListController,
});
