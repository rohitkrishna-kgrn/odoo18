"""Stage configuration is now Admin-only (previously Manager had full
create/write/unlink on client.helpdesk.stage).

security/ir.model.access.csv and the action's groups_id already enforce
this on every upgrade (neither is noupdate-protected), but
record_rules.xml is loaded inside <data noupdate="1">, so the repurposed
rule_stage_manager_all record (now scoped to group_helpdesk_admin instead
of group_helpdesk_manager) won't pick up its new group/name from the data
file on an already-installed database — fixed up explicitly below, same
pattern as 18.0.2.4.0.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    rule = env.ref('client_helpdesk_portal.rule_stage_manager_all', raise_if_not_found=False)
    admin_group = env.ref('client_helpdesk_portal.group_helpdesk_admin', raise_if_not_found=False)
    if rule and admin_group:
        rule.write({
            'name': 'Helpdesk Stage: Admin full access',
            'groups': [(6, 0, [admin_group.id])],
        })
