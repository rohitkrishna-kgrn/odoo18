/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Pops a toast in the corner of whatever page the recipient is on the moment
 * the other side of a ticket conversation writes to them - support team ->
 * ticket creator, ticket creator -> the agent the ticket is assigned to. The
 * server already picked that single recipient and pushed to their own partner
 * channel, so anything arriving here is by definition addressed to this user.
 *
 * Lives in a service rather than in the chat widget because the point is to
 * reach the user while they are somewhere else entirely: the bus connection
 * has to be up from the moment the web client boots, not only while a ticket
 * form happens to be open.
 */
export const helpdeskChatNotificationService = {
    dependencies: ["bus_service", "notification", "action"],

    start(env, { bus_service: busService, notification, action }) {
        // Ticket whose chat panel is open and unfolded right now: the user is
        // already watching those messages arrive, so a toast would be noise.
        const state = { activeTicketId: null };
        // A message is announced exactly once, even if the bus replays a
        // notification after a reconnection.
        const announced = new Set();

        function remember(messageId) {
            announced.add(messageId);
            if (announced.size > 200) {
                announced.delete(announced.values().next().value);
            }
        }

        busService.subscribe("helpdesk_rk_chat_notification", (payload) => {
            if (!payload || !payload.message_id || announced.has(payload.message_id)) {
                return;
            }
            remember(payload.message_id);
            if (state.activeTicketId === payload.ticket_id) {
                return;
            }
            const reference = payload.ticket_number
                ? `${payload.ticket_number} - ${payload.ticket_name}`
                : payload.ticket_name;
            notification.add(payload.preview || _t("Sent you a message."), {
                title: _t("%(author)s - %(ticket)s", {
                    author: payload.author_name,
                    ticket: reference,
                }),
                type: "info",
                autocloseDelay: 8000,
                buttons: [
                    {
                        name: _t("Open Ticket"),
                        primary: true,
                        icon: "fa-external-link",
                        onClick: () =>
                            action.doAction({
                                type: "ir.actions.act_window",
                                res_model: "helpdesk_rk.ticket",
                                res_id: payload.ticket_id,
                                views: [[false, "form"]],
                                target: "current",
                            }),
                    },
                ],
            });
        });

        // subscribe() only registers a handler; the websocket itself is only
        // dialled by start()/addChannel(). Without this the toast would only
        // work on pages where some other feature happened to open the bus.
        busService.start();

        return state;
    },
};

registry.category("services").add("helpdesk_rk.chat_notification", helpdeskChatNotificationService);
