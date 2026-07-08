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
        # This wizard is superseded by the "Commission Paid" button on the commission form.
        # Commission payment now uses a simple Unpaid → Paid workflow.
        from odoo.exceptions import UserError
        raise UserError(
            "Please use the 'Commission Paid' button on the commission form "
            "to mark this commission as paid to the referrer."
        )
