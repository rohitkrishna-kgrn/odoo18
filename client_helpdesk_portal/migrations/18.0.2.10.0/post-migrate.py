"""Force-correct menu_helpdesk_stages.groups_id to Admin-only.

Discovered on the "live" database: the menu's groups_id had accumulated
both Helpdesk Admin AND Helpdesk Manager, even though menu.xml has said
Admin-only since 18.0.2.6.0, ir_model_data.noupdate for this record is
False, and repeated `-u` reloads of menu.xml did not clear the stale
Manager group on their own. Root cause not conclusively identified (most
likely a leftover from the multi-step edit history on that database
rather than a general Odoo bug), but since the drift was real and file
reloads alone didn't self-heal it, force it explicitly here rather than
assume every environment is clean.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    menu = env.ref('client_helpdesk_portal.menu_helpdesk_stages', raise_if_not_found=False)
    admin_group = env.ref('client_helpdesk_portal.group_helpdesk_admin', raise_if_not_found=False)
    if menu and admin_group and menu.groups_id != admin_group:
        menu.write({'groups_id': [(6, 0, [admin_group.id])]})
