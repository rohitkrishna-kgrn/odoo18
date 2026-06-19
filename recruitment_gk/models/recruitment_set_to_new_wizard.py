from markupsafe import Markup, escape
from odoo import models, fields, _


class RecruitmentSetToNewWizard(models.TransientModel):
    _name = 'recruitment.set.to.new.wizard'
    _description = 'Reset Candidate to New Wizard'

    candidate_id = fields.Many2one('recruitment.candidate', required=True, readonly=True)
    remark = fields.Text('Remark', required=True)

    def action_confirm(self):
        candidate = self.candidate_id
        new_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'new')], limit=1
        )
        candidate.state = 'new'
        if new_stage:
            candidate.stage_id = new_stage
        candidate.message_post(
            body=Markup('Candidate reset to <b>New</b> by HR Admin. Remark: %s') % escape(self.remark),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
