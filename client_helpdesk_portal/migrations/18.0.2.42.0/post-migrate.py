"""menu_helpdesk_notification_log used to have a direct action (it was a
single "Notifications" menu item); this version splits it into a parent
category with two children ("All Notifications" and "Reopened Tickets").

Removing the `action="..."` attribute from a <menuitem> tag does not
clear a previously-set action on upgrade -- the loader only writes
attributes actually present in the tag, so an omitted one leaves the
existing value untouched rather than resetting it. Confirmed on the
"live" database: after reloading menu.xml with no `action` on this
menuitem, it was still pointing at the old action. Clear it explicitly.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    menu = env.ref('client_helpdesk_portal.menu_helpdesk_notification_log', raise_if_not_found=False)
    if menu and menu.action:
        menu.write({'action': False})
