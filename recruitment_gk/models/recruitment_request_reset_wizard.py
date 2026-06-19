from markupsafe import Markup, escape
from odoo import models, fields, _


class RecruitmentRequestResetWizard(models.TransientModel):
    _name = 'recruitment.request.reset.wizard'
    _description = 'Reset Recruitment Request to New Wizard'

    request_id = fields.Many2one('recruitment.request', required=True, readonly=True)
    remark = fields.Text('Remark', required=True)

    def action_confirm(self):
        self.request_id.state = 'draft'
        self.request_id.message_post(
            body=Markup('Request reset to <b>New</b> by HR Admin. Remark: %s') % escape(self.remark),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
