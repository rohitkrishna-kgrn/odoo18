"""Collapse the "Notifications" menu back to a single flat item — the
previous version split it into a parent category with "All
Notifications" and "Reopened Tickets" children; this version removes
that split (per request) and restores the direct action on the single
"Notifications" menu, keeping the event_type='reopen' tracking and its
search filter, just not a dedicated menu entry for it.

Removing an id from a data file does not delete its DB record, so the
now-unreferenced child menu and action are unlinked explicitly here.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    menu = env.ref('client_helpdesk_portal.menu_helpdesk_notification_log_reopened', raise_if_not_found=False)
    if menu:
        menu.unlink()

    action = env.ref('client_helpdesk_portal.action_helpdesk_notification_log_reopened', raise_if_not_found=False)
    if action:
        action.unlink()

    # menu_helpdesk_notification_log_all was renamed back to
    # menu_helpdesk_notification_log's own direct action rather than kept
    # as a child — if the "All Notifications" child still exists from the
    # previous version, drop it too; the parent now serves that role.
    old_all_menu = env.ref('client_helpdesk_portal.menu_helpdesk_notification_log_all', raise_if_not_found=False)
    if old_all_menu:
        old_all_menu.unlink()

    parent = env.ref('client_helpdesk_portal.menu_helpdesk_notification_log', raise_if_not_found=False)
    action_all = env.ref('client_helpdesk_portal.action_helpdesk_notification_log', raise_if_not_found=False)
    if parent and action_all and parent.action != action_all:
        parent.write({'action': f'ir.actions.act_window,{action_all.id}'})
