/** @odoo-module **/

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { useService } from "@web/core/utils/hooks";
import { onWillUnmount } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

/**
 * Support/Admin "All Tickets" board: drafts are pre-submission and not yet
 * actionable by the support workflow, so this kanban excludes them
 * entirely (no empty "Draft" column, no draft cards) without touching the
 * List view, which still needs to show every ticket.
 */
class HelpdeskAllTicketsKanbanModel extends RelationalModel {
    _getNextConfig(currentConfig, params) {
        const config = super._getNextConfig(currentConfig, params);
        if (!config.isMonoRecord && config.resModel === "helpdesk_rk.ticket") {
            config.domain = [...(config.domain || []), ["stage_id", "!=", "draft"]];
            config.context = { ...config.context, hide_draft_group: true };
        }
        return config;
    }
}

class HelpdeskAllTicketsKanbanController extends KanbanController {
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

registry.category("views").add("helpdesk_ticket_kanban_all", {
    ...kanbanView,
    Model: HelpdeskAllTicketsKanbanModel,
    Controller: HelpdeskAllTicketsKanbanController,
});
