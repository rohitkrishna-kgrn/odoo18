from odoo import models, fields, _
from odoo.exceptions import UserError
from markupsafe import Markup


class UpsellingResubmitWizard(models.TransientModel):
    _name = 'upselling.resubmit.wizard'
    _description = 'Upselling Resubmission Wizard'

    upselling_id = fields.Many2one('upselling', string='Upselling', required=True)
    remark = fields.Text(string='Remark', required=True)

    def action_confirm_resubmit(self):
        self.ensure_one()
        rec = self.upselling_id
        if rec.state == 'rejected':
            raise UserError(_(
                'Upselling request %s has been rejected and cannot be sent back for '
                'resubmission.'
            ) % rec.sequence)
        rec.state = 'draft'
        rec.message_post(
            body=Markup('<span style="color:#1a73e8;">Remark :</span> <span style="color:#000000;">{}</span>').format(self.remark),
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return {'type': 'ir.actions.act_window_close'}
