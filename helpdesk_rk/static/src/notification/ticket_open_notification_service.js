/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Pops a toast for every ticket conversation that has unread messages,
 * once, the moment the user opens Odoo (webclient boot). This is the
 * counterpart to helpdesk_rk.chat_notification: that service only reacts to
 * messages sent while the user's session is already connected to the bus,
 * so anything sent while they were logged out would otherwise surface
 * nowhere except the bell icon on the kanban/list boards.
 */
export const helpdeskTicketOpenNotificationService = {
    dependencies: ["orm", "notification", "action", "menu"],

    start(env, { orm, notification, action, menu }) {
        // A raw ad-hoc act_window dict opens the ticket form fine, but only
        // menuService's own selectMenu() ever switches the left app menu -
        // a dict action has no matching ir.ui.menu for it to find. Routing
        // through the ticket's real menu action, then calling setCurrentMenu
        // ourselves (exactly as selectMenu does), makes this button behave
        // like an actual click on the Helpdesk menu.
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

        orm
            .call("helpdesk_rk.ticket", "get_unread_chat_notifications", [])
            .then((tickets) => {
                for (const ticket of tickets) {
                    const reference = ticket.ticket_number
                        ? `${ticket.ticket_number} - ${ticket.ticket_name}`
                        : ticket.ticket_name;
                    // notification.add() returns a closer for this exact
                    // toast - the button's own onClick has to call it, since
                    // clicking a button does not dismiss the toast on its own.
                    const closeToast = notification.add(
                        _t("%(count)s unread message(s).", { count: ticket.unread_count }),
                        {
                            title: reference,
                            type: "info",
                            autocloseDelay: 5000,
                            buttons: [
                                {
                                    name: _t("Open Ticket"),
                                    primary: true,
                                    icon: "fa-external-link",
                                    onClick: () => {
                                        closeToast();
                                        openTicket(ticket.ticket_id);
                                    },
                                },
                            ],
                        }
                    );
                }
            })
            .catch(() => {});
    },
};

registry.category("services").add("helpdesk_rk.ticket_open_notification", helpdeskTicketOpenNotificationService);
