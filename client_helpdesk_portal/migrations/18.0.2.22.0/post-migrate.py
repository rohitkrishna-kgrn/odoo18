"""Backfill reopened_date for tickets that were already sitting in the
Reopened stage before that field existed (18.0.2.21.0) — otherwise they
never qualify for a Reopened-stage reminder, since nothing sets the
field until the ticket cycles through Closed -> Reopened again.

Best available reference: the ticket's latest 'reopen' reason-line
date_time (logged by action_reopen_by_client), falling back to
write_date if a ticket is Reopened but has no reason-line for some
reason.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    stage = env['client.helpdesk.stage'].search([('name', '=', 'Reopened')], limit=1)
    if not stage:
        return
    tickets = env['client.helpdesk.ticket'].search([
        ('stage_id', '=', stage.id), ('reopened_date', '=', False),
    ])
    for ticket in tickets:
        last_reopen = env['client.helpdesk.reason.line'].search([
            ('ticket_id', '=', ticket.id), ('action_type', '=', 'reopen'),
        ], order='date_time desc', limit=1)
        ticket.reopened_date = last_reopen.date_time if last_reopen else ticket.write_date
