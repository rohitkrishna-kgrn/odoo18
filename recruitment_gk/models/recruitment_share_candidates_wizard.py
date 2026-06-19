from odoo import models, fields, _
from odoo.exceptions import UserError


class RecruitmentShareCandidatesWizard(models.TransientModel):
    _name = 'recruitment.share.candidates.wizard'
    _description = 'Share Candidates with Hiring Manager'

    request_id = fields.Many2one('recruitment.request', required=True, readonly=True)
    hiring_manager_id = fields.Many2one(
        'res.users', 'Hiring Manager',
        required=True,
        domain=[('share', '=', False)],
    )
    candidate_ids = fields.Many2many('recruitment.candidate', string='Candidates')

    def action_share_candidates(self):
        if not self.candidate_ids:
            raise UserError(_('Please select at least one candidate to share.'))

        self.candidate_ids.write({
            'request_id': self.request_id.id,
            'state': 'manager_review',
        })

        vals = {'candidates_shared': True}
        if self.hiring_manager_id != self.request_id.user_id:
            vals['user_id'] = self.hiring_manager_id.id
        self.request_id.write(vals)

        # Notify only the specific Hiring Manager — one email per candidate (req. 2)
        for candidate in self.candidate_ids:
            self.env['recruitment.request']._send_template_email(
                'email_template_candidate_to_review',
                candidate,
                extra_recipients=self.hiring_manager_id,
            )

        return {'type': 'ir.actions.act_window_close'}
