from odoo import api, models, fields, _


class SaleOrderAdvanceConfirmWizard(models.TransientModel):
    _name = 'sale.order.advance.confirm.wizard'
    _description = 'Advance Payment Confirmation Wizard'

    order_id = fields.Many2one('sale.order', string='Sale Order', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', readonly=True)
    advance_amount = fields.Monetary(string='Advance Amount', readonly=True, currency_field='currency_id')
    paid_amount = fields.Monetary(string='Paid Amount', readonly=True, currency_field='currency_id')
    recurring_not_setup = fields.Boolean(
        string='Recurring Not Set Up',
        compute='_compute_recurring_not_setup',
    )

    @api.depends('order_id')
    def _compute_recurring_not_setup(self):
        for rec in self:
            order = rec.order_id
            # Guard: kgrn_recurring_payment may not be installed
            if 'is_recurring' not in order._fields or not order.is_recurring:
                rec.recurring_not_setup = False
                continue
            contract = order.kgrn_recurring_contract_id
            state = order.kgrn_recurring_contract_state
            rec.recurring_not_setup = not contract or state == 'draft'

    def action_confirm_order(self):
        self.ensure_one()
        self.order_id.with_context(skip_advance_check=True).action_confirm()
        return {'type': 'ir.actions.act_window_close'}

    def action_discard(self):
        return {'type': 'ir.actions.act_window_close'}
