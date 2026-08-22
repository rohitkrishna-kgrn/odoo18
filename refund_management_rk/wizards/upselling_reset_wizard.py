from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class UpsellingResetWizard(models.TransientModel):
    _name = 'upselling.reset.wizard'
    _description = 'Upselling Reset to Review Wizard'

    upselling_id = fields.Many2one('upselling', string='Upselling', required=True)
    reason = fields.Text(string='Reason / Remark', required=True)

    @api.constrains('reason')
    def _check_reason(self):
        for wizard in self:
            if not (wizard.reason or '').strip():
                raise ValidationError(_(
                    'A reason/remark is mandatory to reset the request to review.'
                ))

    def action_confirm_reset(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_(
                'A reason/remark is mandatory to reset the request to review.'
            ))
        self.upselling_id._reset_to_review(reason)
        return {'type': 'ir.actions.act_window_close'}
