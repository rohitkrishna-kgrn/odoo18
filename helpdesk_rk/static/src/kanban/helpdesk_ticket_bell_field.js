/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { ignoreDestroyedComponentError } from "../utils/silence_destroyed_error";

const CLOSED_STAGES = ["done", "rejected"];

/**
 * Bell icon showing unread ticket-chat messages from the other party
 * (Client <-> Support Team). Once a ticket is Done/Rejected the bell is
 * replaced by a disabled/crossed icon and stops showing a count.
 *
 * Subscribes to this ticket's chat bus channel so the unread count updates
 * live when the other party sends a message, without a page refresh.
 */
export class HelpdeskTicketBellField extends Component {
    static template = "helpdesk_rk.TicketBellField";
    static props = { ...standardFieldProps };

    setup() {
        this.busService = useService("bus_service");
        this.busChannel = null;
        this.onBusNotification = this.onBusNotification.bind(this);
        this.busService.subscribe("helpdesk_rk_chat_message", this.onBusNotification);

        onMounted(() => this.subscribeToBus());
        onWillUnmount(() => {
            this.busService.unsubscribe("helpdesk_rk_chat_message", this.onBusNotification);
            if (this.busChannel) {
                this.busService.deleteChannel(this.busChannel);
            }
        });
    }

    get resId() {
        return this.props.record.resId;
    }

    subscribeToBus() {
        if (this.resId && !this.isClosed) {
            this.busChannel = `helpdesk_rk.ticket_chat_${this.resId}`;
            this.busService.addChannel(this.busChannel);
        }
    }

    onBusNotification(payload) {
        if (payload.ticket_id === this.resId) {
            ignoreDestroyedComponentError(this.props.record.load());
        }
    }

    get isClosed() {
        return CLOSED_STAGES.includes(this.props.record.data.stage_id);
    }

    get unreadCount() {
        return this.props.record.data[this.props.name] || 0;
    }

    get unreadLabel() {
        return `${this.unreadCount}+`;
    }

    get title() {
        if (this.isClosed) {
            return "Conversation closed";
        }
        return this.unreadCount ? `${this.unreadCount} unread message(s)` : "No unread messages";
    }
}

export const helpdeskTicketBellField = {
    component: HelpdeskTicketBellField,
    fieldDependencies: [{ name: "stage_id", type: "selection" }],
};

registry.category("fields").add("helpdesk_ticket_bell", helpdeskTicketBellField);
