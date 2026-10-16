from odoo import models, fields, _
from odoo.exceptions import UserError


class UpsellingResetDraftWizard(models.TransientModel):
    _name = 'upselling.reset.draft.wizard'
    _description = 'Upselling Reset to Draft Wizard'

    upselling_id = fields.Many2one('upselling', string='Upselling', required=True)
    reasons = fields.Text(
        string='Reasons', required=True,
        help='One reason per line (entered as chips in the form).',
    )

    def action_confirm_reset_draft(self):
        self.ensure_one()
        if not (self.reasons or '').strip():
            raise UserError(_('Enter at least one reason to reset the request to draft.'))
        self.upselling_id._reset_to_draft(self.reasons)
        return {'type': 'ir.actions.act_window_close'}
