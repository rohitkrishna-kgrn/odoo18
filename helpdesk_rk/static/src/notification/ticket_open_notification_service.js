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
    dependencies: ["orm", "notification", "action"],

    start(env, { orm, notification, action }) {
        orm
            .call("helpdesk_rk.ticket", "get_unread_chat_notifications", [])
            .then((tickets) => {
                for (const ticket of tickets) {
                    const reference = ticket.ticket_number
                        ? `${ticket.ticket_number} - ${ticket.ticket_name}`
                        : ticket.ticket_name;
                    notification.add(
                        _t("%(count)s unread message(s).", { count: ticket.unread_count }),
                        {
                            title: reference,
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
                                            res_id: ticket.ticket_id,
                                            views: [[false, "form"]],
                                            target: "current",
                                        }),
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
