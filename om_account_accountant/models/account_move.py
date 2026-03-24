from odoo import fields, models, api


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.model
    def _get_invoice_in_payment_state(self):
        return 'in_payment'

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    product_id = fields.Many2one('product.product', string='Service')