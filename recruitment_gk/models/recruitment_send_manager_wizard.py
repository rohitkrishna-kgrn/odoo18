from markupsafe import Markup, escape
from odoo import models, fields, _


class RecruitmentSendManagerWizard(models.TransientModel):
    _name = 'recruitment.send.manager.wizard'
    _description = 'Send Candidate to Manager'

    candidate_id = fields.Many2one('recruitment.candidate', required=True)
    manager_id = fields.Many2one(
        'res.users', 'Hiring Manager', required=True,
        domain=lambda self: [('groups_id', 'in', [
            self.env.ref('recruitment_gk.group_recruitment_hiring_manager').id
        ])],
    )

    def action_confirm(self):
        stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'manager_review')], limit=1
        )
        candidate = self.candidate_id
        candidate.sent_manager_id = self.manager_id
        candidate.state = 'manager_review'
        if stage:
            candidate.stage_id = stage
        candidate.message_post(
            body=Markup('Candidate sent to <b>%s</b> for review.') % escape(self.manager_id.name),
            subtype_xmlid='mail.mt_note',
        )
        # Notify the selected Hiring Manager by email with candidate details
        self.env['recruitment.request']._send_template_email(
            'email_template_candidate_to_review',
            candidate,
            extra_recipients=self.manager_id,
        )
        return {'type': 'ir.actions.act_window_close'}
