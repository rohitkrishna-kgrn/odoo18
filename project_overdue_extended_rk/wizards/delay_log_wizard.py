from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.misc import format_date


class ProjectDelayLogWizard(models.TransientModel):
    """Popup asking why a project / task blew past its deadline.

    Raised automatically by the form controller when such a record is opened
    with no delay log on file. Submitting writes the reason onto the record
    (which is what clears the `delay_log_missing` flag and flips the list badge)
    and logs it in the chatter, so successive explanations stay on the record's
    own timeline instead of overwriting each other silently.
    """

    _name = 'project.delay.log.wizard'
    _description = 'Delay Reason Log'

    res_model = fields.Selection(
        selection=[
            ('project.project', 'Project'),
            ('project.task', 'Task'),
        ],
        string='Record Model',
        required=True,
    )
    res_id = fields.Integer(string='Record ID', required=True)
    record_name = fields.Char(string='Record', readonly=True)
    deadline = fields.Date(string='Deadline', readonly=True)
    days_overdue = fields.Integer(
        string='Days Overdue',
        compute='_compute_days_overdue',
    )
    reason = fields.Text(string='Reason for the Delay', required=True)
    revised_date = fields.Date(string='Revised Delivery Date')

    @api.depends('deadline')
    def _compute_days_overdue(self):
        today = fields.Date.today()
        for wizard in self:
            wizard.days_overdue = (today - wizard.deadline).days if wizard.deadline else 0

    def _get_record(self):
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_("The record this delay log belongs to no longer exists."))
        return record

    def _delay_log_body(self):
        """Chatter body for the submitted log.

        Built with Markup because message_post() escapes a plain str: HTML in a
        _() call would otherwise reach the chatter as literal <p> tags.
        """
        self.ensure_one()
        parts = [Markup("<p><b>%s</b></p>") % _("Delay reason logged")]
        if self.deadline:
            parts.append(Markup("<p>%s</p>") % _(
                "Deadline %(deadline)s — %(days)s day(s) overdue.",
                deadline=format_date(self.env, self.deadline),
                days=self.days_overdue,
            ))
        parts.append(
            Markup("<p>%s<br/>%s</p>") % (
                Markup("<b>%s</b>") % _("Reason:"),
                Markup("<br/>").join((self.reason or '').splitlines()),
            )
        )
        if self.revised_date:
            parts.append(Markup("<p>%s %s</p>") % (
                Markup("<b>%s</b>") % _("Revised delivery date:"),
                format_date(self.env, self.revised_date),
            ))
        return Markup("").join(parts)

    def action_submit(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("Please describe the reason for the delay."))

        record = self._get_record()
        vals = {'delay_reason': reason}
        if self.revised_date:
            vals['delay_revised_date'] = self.revised_date

        # sudo(): filing the delay log is a compliance step every assignee must
        # be able to complete, but project.project is read-only for non-managers
        # and mail.thread._mail_post_access defaults to 'write'. sudo() only
        # flips `su` — env.uid is untouched — so the chatter message is still
        # authored by the acting user.
        record.sudo().write(vals)
        record.sudo().message_post(
            body=self._delay_log_body(),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
