"""Send a one-off copy of a deadline alert, to check format and delivery.

The live feature only speaks once a deadline is inside its window, which makes
it awkward to verify: there is no way to ask "what will this look like, and
will it actually arrive?" without waiting for a real deadline to come round.

This wizard answers both questions on demand. It renders the real alert body
through the same mixin the cron uses — so what is checked here is the message
that will really go out — and it reports the SMTP server's own answer back,
rather than leaving a failed send to be discovered in the mail queue later.

It is read-only with respect to the feature: the ``..._sent_for`` stamps are
untouched and no To-Do is raised, so testing never suppresses a real alert.
"""

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DeadlineAlertTestWizard(models.TransientModel):
    _name = 'deadline.alert.test.wizard'
    _description = 'Send Test Deadline Alert'

    target_model = fields.Selection(
        [('project.task', 'Task'), ('project.project', 'Project')],
        string='Send About', required=True, default='project.task',
        help="Tasks are the useful case today: no project in this database "
             "has its Deadline field filled in, so a project test needs a "
             "simulated deadline below.",
    )
    task_id = fields.Many2one('project.task', string='Task')
    project_id = fields.Many2one('project.project', string='Project')

    kind = fields.Selection(
        [('advance', 'Advance warning (before the deadline)'),
         ('due', 'On the deadline date')],
        string='Alert', required=True, default='advance',
    )

    recipient_ids = fields.Many2many(
        'res.users', string='Send To', required=True,
        domain="[('active','=',True), ('share','=',False)]",
        default=lambda self: self.env.user,
        help="Defaults to you. The live alert goes to the Project Manager and "
             "the department head instead — see the preview below.",
    )

    simulated_deadline = fields.Date(
        string='Simulate Deadline',
        help="Leave empty to use the record's own deadline. Set it to preview "
             "a different day, or to test a record that has no deadline yet.",
    )

    inbox_copy = fields.Boolean(
        string='Also copy to Odoo inbox', default=False,
        help="Off by default: the test is an email. Tick this only if you "
             "also want the message readable inside Odoo without waiting on "
             "the outgoing mail server.",
    )

    preview_html = fields.Html(
        string='Preview', compute='_compute_preview_html', sanitize=False,
        help="Exactly what the recipients will be sent.",
    )

    live_recipients_preview = fields.Char(
        string='Live Alert Would Go To', compute='_compute_live_recipients_preview',
        help="Who the scheduled alert would actually notify for this record.",
    )
    deadline_preview = fields.Char(
        string="Record's Deadline", compute='_compute_deadline_preview',
    )

    # ------------------------------------------------------------------

    def _target_record(self):
        """The record under test, or an empty recordset."""
        self.ensure_one()
        if self.target_model == 'project.task':
            return self.task_id
        return self.project_id

    @api.depends('target_model', 'task_id', 'project_id', 'kind',
                 'simulated_deadline')
    def _compute_preview_html(self):
        for wizard in self:
            record = wizard._target_record()
            deadline = wizard.simulated_deadline or (
                record._deadline_alert_date() if record else False)
            if not record or not deadline:
                wizard.preview_html = False
                continue
            wizard.preview_html = record._deadline_alert_test_body(
                wizard.kind, deadline)

    @api.depends('target_model', 'task_id', 'project_id')
    def _compute_live_recipients_preview(self):
        for wizard in self:
            record = wizard._target_record()
            if not record:
                wizard.live_recipients_preview = ''
                continue
            users = record._deadline_alert_recipients()
            wizard.live_recipients_preview = ', '.join(
                '%s <%s>' % (u.name, u.email or _('no email')) for u in users
            ) or _('nobody — the alert would post to the record only')

    @api.depends('target_model', 'task_id', 'project_id')
    def _compute_deadline_preview(self):
        for wizard in self:
            record = wizard._target_record()
            deadline = record._deadline_alert_date() if record else False
            wizard.deadline_preview = (
                fields.Date.to_string(deadline) if deadline
                else _('not set — fill in Simulate Deadline')
            )

    # ------------------------------------------------------------------

    def action_send_test(self):
        self.ensure_one()
        record = self._target_record()
        if not record:
            raise UserError(_("Pick the record to send the test alert about."))

        results = record._deadline_alert_send_test(
            self.recipient_ids,
            kind=self.kind,
            deadline=self.simulated_deadline or None,
            inbox_copy=self.inbox_copy,
        )

        # results are (email, state, reason)
        sent = [r for r in results if r[1] == 'sent']
        failed = [r for r in results if r[1] == 'exception']
        pending = [r for r in results if r[1] not in ('sent', 'exception')]

        lines = [_(
            "%(count)s test email(s) created. Find them under Settings > "
            "Technical > Email > Emails.", count=len(results),
        )]
        if self.inbox_copy:
            lines.append(_(
                "A copy was also placed in the Odoo inbox of %(names)s.",
                names=', '.join(self.recipient_ids.mapped('name')),
            ))
        if sent:
            lines.append(_("Sent to %(addresses)s.",
                           addresses=', '.join(r[0] for r in sent)))
        if pending:
            lines.append(_("Still queued for %(addresses)s.",
                           addresses=', '.join(r[0] for r in pending)))
        if failed:
            # Surface the server's own words. A silent failure here is exactly
            # what this wizard exists to prevent.
            reason = (failed[0][2] or _('no reason reported'))[:300]
            lines.append(_(
                "NOT delivered to %(addresses)s. The outgoing mail server "
                "rejected the message: %(reason)s",
                addresses=', '.join(r[0] for r in failed), reason=reason,
            ))
            lines.append(_(
                "The email itself is correct and is sitting in the queue — fix "
                "the outgoing mail server, then select it there and retry."
            ))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Test Deadline Alert'),
                'message': '\n'.join(lines),
                'type': 'warning' if failed else 'success',
                'sticky': True,
            },
        }
