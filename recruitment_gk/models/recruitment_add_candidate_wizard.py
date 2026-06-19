from odoo import models, fields, _


class RecruitmentAddCandidateWizard(models.TransientModel):
    _name = 'recruitment.add.candidate.wizard'
    _description = 'Add Candidates to Recruitment Request'

    request_id = fields.Many2one('recruitment.request', required=True, readonly=True)
    candidate_ids = fields.Many2many('recruitment.candidate', string='Candidates')

    def action_add_candidates(self):
        self.candidate_ids.write({'request_id': self.request_id.id})
        for candidate in self.candidate_ids:
            self.env['recruitment.request']._send_template_email(
                'email_template_candidate_added', candidate,
            )
        return {'type': 'ir.actions.act_window_close'}
