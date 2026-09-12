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
    dependencies: ["bus_service", "notification", "action", "menu"],

    start(env, { bus_service: busService, notification, action, menu }) {
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

        // A plain ad-hoc act_window dict opens the ticket form fine, but the
        // web client only ever switches the left app menu from menuService's
        // own selectMenu() - a raw dict has no matching ir.ui.menu, so the
        // navbar silently stays on whatever app the user was already in.
        // Routing through the ticket's real menu action (and calling
        // setCurrentMenu ourselves, exactly as selectMenu does) makes this
        // button behave like an actual click on the Helpdesk menu.
        //
        // NB: menusData's "actionModel" is the polymorphic type of the
        // *action* record itself (always "ir.actions.act_window" for these),
        // never the res_model it opens - matching on it can never find
        // anything. The menu's xmlid is what's actually unique per entry, so
        // match on the two known Helpdesk-ticket menu xmlids instead; only
        // one of them is visible to any given user (support/admin get "All
        // Tickets", everyone else in the Helpdesk User group gets "Tickets").
        const HELPDESK_TICKET_MENU_XMLIDS = [
            "helpdesk_rk.menu_helpdesk_tickets_all",
            "helpdesk_rk.menu_helpdesk_tickets_own",
        ];
        function openTicket(ticketId) {
            const ticketMenu = menu
                .getAll()
                .find((m) => HELPDESK_TICKET_MENU_XMLIDS.includes(m.xmlid));
            if (ticketMenu) {
                action.doAction(ticketMenu.actionID, {
                    props: { resId: ticketId },
                    clearBreadcrumbs: true,
                    onActionReady: () => menu.setCurrentMenu(ticketMenu),
                });
            } else {
                action.doAction({
                    type: "ir.actions.act_window",
                    res_model: "helpdesk_rk.ticket",
                    res_id: ticketId,
                    views: [[false, "form"]],
                    target: "current",
                });
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
            // notification.add() returns a closer for this exact toast - the
            // button's own onClick has to call it, since clicking a button
            // does not dismiss the toast on its own.
            const closeToast = notification.add(payload.preview || _t("Sent you a message."), {
                title: _t("%(author)s - %(ticket)s", {
                    author: payload.author_name,
                    ticket: reference,
                }),
                type: "info",
                autocloseDelay: 5000,
                buttons: [
                    {
                        name: _t("Open Ticket"),
                        primary: true,
                        icon: "fa-external-link",
                        onClick: () => {
                            closeToast();
                            openTicket(payload.ticket_id);
                        },
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
