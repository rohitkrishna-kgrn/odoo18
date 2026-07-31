"""Undo the New/In Progress/Done/Closed/Reopened stage collapse introduced
in 18.0.2.3.0, restoring the original New / Under Review / In Progress /
Waiting for Client / Resolved / Closed / Reopened flow. Only the "Rejected"
removal from that version is kept.

18.0.2.3.0 already ran for real on the live database before this reversal
was requested, so this migration operates on its *result*:
  - stage_in_progress / stage_resolved / stage_closed / stage_reopened
    already exist (noupdate=1 blocks the data file from re-applying their
    name/sequence on its own) — fixed up explicitly below.
  - stage_under_review / stage_waiting no longer exist (they were unlinked
    by 18.0.2.3.0) — the reverted data file recreates them fresh with the
    same external ids, sequence 2 and 4, via normal data loading; nothing
    to do for them here.

Important limitation: 18.0.2.3.0 merged "Under Review" and "Waiting for
Client" tickets into "In Progress" and did not keep a record of which was
which. That distinction cannot be reconstructed automatically — any ticket
currently in "In Progress" stays there; an agent can manually move it back
to "Under Review" or "Waiting for Client" if needed (the change history is
still visible in each ticket's chatter).

Also removes any stage literally named "Rejected" (e.g. one added ad-hoc
via the Stages configuration screen) — any ticket still in it is moved to
"Closed" first so nothing is left pointing at a deleted stage.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Stage = env['client.helpdesk.stage']
    Ticket = env['client.helpdesk.ticket']

    stage_in_progress = env.ref('client_helpdesk_portal.stage_in_progress', raise_if_not_found=False)
    stage_resolved = env.ref('client_helpdesk_portal.stage_resolved', raise_if_not_found=False)
    stage_closed = env.ref('client_helpdesk_portal.stage_closed', raise_if_not_found=False)
    stage_reopened = env.ref('client_helpdesk_portal.stage_reopened', raise_if_not_found=False)

    if stage_in_progress and stage_in_progress.sequence != 3:
        stage_in_progress.sequence = 3
    if stage_resolved and (stage_resolved.name != 'Resolved' or stage_resolved.sequence != 5):
        stage_resolved.write({'name': 'Resolved', 'sequence': 5})
    if stage_closed and stage_closed.sequence != 6:
        stage_closed.sequence = 6
    if stage_reopened and stage_reopened.sequence != 7:
        stage_reopened.sequence = 7

    rejected_stages = Stage.search([('name', '=', 'Rejected')])
    if rejected_stages:
        stray_tickets = Ticket.search([('stage_id', 'in', rejected_stages.ids)])
        if stray_tickets and stage_closed:
            stray_tickets.write({'stage_id': stage_closed.id})
        rejected_stages.unlink()

    PortalUser = env['client.helpdesk.portal.user']
    Employee = env['hr.employee']
    already_configured = PortalUser.with_context(active_test=False).search([]).mapped('employee_id').ids
    missing = Employee.search([('active', '=', True), ('id', 'not in', already_configured or [0])])
    PortalUser.create([{'employee_id': emp.id} for emp in missing])
