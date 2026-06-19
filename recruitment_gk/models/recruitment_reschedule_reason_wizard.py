from odoo import models, fields, _
from odoo.exceptions import UserError


class RecruitmentRescheduleReasonWizard(models.TransientModel):
    _name = 'recruitment.reschedule.reason.wizard'
    _description = 'Interview Reschedule Reason'

    interview_round_id = fields.Many2one(
        'recruitment.interview.round', 'Interview Round',
        required=True, ondelete='cascade', readonly=True,
    )
    reason = fields.Text('Reason for Rescheduling', required=True)

    def action_confirm_reschedule(self):
        self.ensure_one()
        rnd = self.interview_round_id
        if not rnd.invitation_sent:
            raise UserError(_('You can only reschedule after an interview invitation has been sent.'))
        if rnd.state != 'scheduled':
            raise UserError(_('Only scheduled rounds can be rescheduled.'))
        return rnd._do_reschedule(self.reason)
