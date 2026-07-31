"""Notification emails are now built entirely in Python
(client.helpdesk.ticket._build_email) with the new orange/white brand,
rather than through mail.template QWeb records — having both a template
and a Python-string fallback (the previous design) meant two different
HTML sources could drift out of sync, which is exactly what happened
with the old navy-blue templates vs. the Python fallbacks.

data/mail_templates.xml (and its 5 records) is removed from the module
entirely. Since these were noupdate="0", Odoo would otherwise leave them
behind as unused, stale-branded orphans in Settings > Email Templates —
unlink them explicitly.
"""
from odoo import api, SUPERUSER_ID

TEMPLATE_XMLIDS = [
    'mail_template_ticket_acknowledgement',
    'mail_template_agent_assignment',
    'mail_template_stage_update_client',
    'mail_template_manager_on_assignment',
    'mail_template_ticket_reopened',
]


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in TEMPLATE_XMLIDS:
        template = env.ref(f'client_helpdesk_portal.{xmlid}', raise_if_not_found=False)
        if template:
            template.unlink()
