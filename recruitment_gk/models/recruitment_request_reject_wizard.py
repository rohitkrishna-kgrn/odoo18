from odoo import models, fields, _


class RecruitmentRequestRejectWizard(models.TransientModel):
    _name = 'recruitment.request.reject.wizard'
    _description = 'Reject Recruitment Request Wizard'

    request_id = fields.Many2one(
        'recruitment.request', 'Recruitment Request',
        required=True, ondelete='cascade', readonly=True,
    )
    rejection_remark = fields.Text('Rejection Remark', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.request_id.write({
            'state': 'rejected',
            'rejection_remark': self.rejection_remark,
        })
        self.request_id.message_post(
            body=_('Request rejected. Reason: %s') % self.rejection_remark,
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
