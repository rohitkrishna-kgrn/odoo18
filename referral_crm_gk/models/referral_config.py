from odoo import api, fields, models


class ReferralConfig(models.TransientModel):
    _name = 'referral.config'
    _description = 'Referral System Settings'

    commission_basis = fields.Selection([
        ('first', 'First Contact Date'),
        ('last', 'Last Contact Date'),
    ], string='Commission Calculation Basis', default='first')

    auto_assign = fields.Boolean(
        string='Auto-assign Salesperson',
        default=False,
    )

    ref_format = fields.Char(
        string='Referral Reference Format',
        default='REF-YYYY-####',
    )

    send_welcome_email = fields.Boolean(
        string='Send Welcome Email on Registration',
        default=False,
    )

    min_payout = fields.Float(
        string='Minimum Payout Threshold (AED)',
        default=0.0,
        digits=(16, 2),
    )

    payout_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
    ], string='Payout Frequency', default='monthly')

    bank_details = fields.Text(
        string='Bank Transfer Details',
    )

    @api.model
    def action_open_settings(self):
        rec = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': 'Referral Settings',
            'res_model': 'referral.config',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }
