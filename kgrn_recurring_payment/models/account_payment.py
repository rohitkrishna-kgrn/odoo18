from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    kgrn_recurring_contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Recurring Contract',
        readonly=True,
        copy=False,
        index=True,
    )
    kgrn_sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        readonly=True,
        copy=False,
        index=True,
        help='Sale order this recurring payment was collected for.',
    )
