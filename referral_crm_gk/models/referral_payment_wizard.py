from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ReferralPaymentWizard(models.TransientModel):
    _name = 'referral.payment.wizard'
    _description = 'Commission Payment Wizard'

    commission_id = fields.Many2one(
        'referral.commission', string='Commission',
        required=True, readonly=True,
    )
    commission_name = fields.Char(
        related='commission_id.name', string='Reference', readonly=True,
    )
    commission_amount = fields.Float(
        related='commission_id.commission_amount',
        string='Total Commission (AED)', readonly=True, digits=(16, 2),
    )
    amount_paid_so_far = fields.Float(
        related='commission_id.amount_paid',
        string='Already Paid (AED)', readonly=True, digits=(16, 2),
    )
    remaining_balance = fields.Float(
        related='commission_id.remaining_balance',
        string='Remaining Balance (AED)', readonly=True, digits=(16, 2),
    )

    payment_type = fields.Selection([
        ('partial', 'Partial Payment'),
        ('full', 'Full Payment'),
    ], string='Payment Type', required=True, default='full')

    amount_being_paid = fields.Float(
        string='Amount Being Paid (AED)', digits=(16, 2),
    )
    payment_ref = fields.Char(string='Cheque / Reference No.', required=True)
    paid_date = fields.Date(string='Payment Date', default=fields.Date.today, required=True)
    notes = fields.Text(string='Notes')

    @api.onchange('payment_type')
    def _onchange_payment_type(self):
        if self.payment_type == 'full':
            self.amount_being_paid = self.remaining_balance or self.commission_amount

    def action_confirm(self):
        self.ensure_one()
        commission = self.commission_id

        if self.payment_type == 'full':
            new_amount_paid = commission.commission_amount
            new_state = 'paid'
        else:
            if not self.amount_being_paid or self.amount_being_paid <= 0:
                raise ValidationError('Please enter a valid amount for the partial payment.')
            if self.amount_being_paid > commission.remaining_balance + 0.001:
                raise ValidationError(
                    f'Amount being paid (AED {self.amount_being_paid:,.2f}) exceeds the '
                    f'remaining balance (AED {commission.remaining_balance:,.2f}). '
                    f'Select Full Payment instead.'
                )
            new_amount_paid = commission.amount_paid + self.amount_being_paid
            new_remaining = commission.commission_amount - new_amount_paid
            new_state = 'paid' if new_remaining <= 0.001 else 'partial'

        commission.write({
            'state': new_state,
            'amount_paid': new_amount_paid,
            'paid_date': self.paid_date,
            'payment_ref': self.payment_ref,
            'notes': self.notes or commission.notes,
        })

        # Sync payment status back to the linked lead
        if commission.lead_id:
            if new_state == 'paid':
                commission.lead_id.sudo().x_payment_status = 'full'
            else:
                commission.lead_id.sudo().x_payment_status = 'partial'

        commission._notify_commission_paid()
        return {'type': 'ir.actions.act_window_close'}
