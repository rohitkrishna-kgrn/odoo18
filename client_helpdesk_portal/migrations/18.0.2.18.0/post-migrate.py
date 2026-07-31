"""Rename the "Helpdesk Agent" role to "Helpdesk User" everywhere it's
displayed (Settings > Users group picker, technical Record Rules list).
Internal identifiers (group_helpdesk_agent, rule_ticket_agent_assigned,
rule_stage_agent_read, etc.) are deliberately left unchanged — only the
display text changed, so no group-membership impact.

security/security.xml and security/record_rules.xml are both loaded
inside <data noupdate="1">, so the name field changes on these existing
records won't reach an already-installed database on a plain module
reload — pushed through explicitly here, same pattern as prior versions.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    group = env.ref('client_helpdesk_portal.group_helpdesk_agent', raise_if_not_found=False)
    if group:
        group.write({'name': 'Helpdesk User'})

    rule_ticket = env.ref('client_helpdesk_portal.rule_ticket_agent_assigned', raise_if_not_found=False)
    if rule_ticket:
        rule_ticket.write({'name': 'Helpdesk Ticket: Helpdesk User sees assigned'})

    rule_stage = env.ref('client_helpdesk_portal.rule_stage_agent_read', raise_if_not_found=False)
    if rule_stage:
        rule_stage.write({'name': 'Helpdesk Stage: Helpdesk User/Manager read only'})
