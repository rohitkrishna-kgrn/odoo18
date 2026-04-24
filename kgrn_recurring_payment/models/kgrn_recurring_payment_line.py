from odoo import fields, models


class KgrnRecurringPaymentLine(models.Model):
    _name = 'kgrn.recurring.payment.line'
    _description = 'KGRN Recurring Payment Line'
    _order = 'payment_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True)

    contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='contract_id.customer_id',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        required=True,
    )
    period_start = fields.Date(string='Period Start', required=True)
    period_end = fields.Date(string='Period End', required=True)
    payment_date = fields.Date(string='Payment Date', required=True)

    state = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('success', 'Succeeded'),
            ('failed', 'Failed'),
            ('refunded', 'Refunded'),
        ],
        string='Status',
        default='pending',
        required=True,
    )

    stripe_payment_intent_id = fields.Char(
        string='Stripe Payment Intent ID',
        readonly=True,
        copy=False,
    )
    failure_reason = fields.Text(string='Failure Reason', readonly=True)

    account_payment_id = fields.Many2one(
        'account.payment',
        string='Accounting Payment',
        readonly=True,
        copy=False,
    )
    processed_by = fields.Many2one(
        'res.users',
        string='Processed By',
        readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        related='contract_id.sale_order_id',
        store=True,
        readonly=True,
    )

    def action_view_account_payment(self):
        self.ensure_one()
        if not self.account_payment_id:
            return {}
        return {
            'type': 'ir.actions.act_window',
            'name': 'Account Payment',
            'res_model': 'account.payment',
            'view_mode': 'form',
            'res_id': self.account_payment_id.id,
        }
