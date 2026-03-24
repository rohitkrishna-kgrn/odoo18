from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

class SaleOrderInvoiceWizard(models.TransientModel):
    _name = 'sale.order.invoice.wizard'
    _description = 'Create Partial Invoice Wizard'

    sale_order_id = fields.Many2one('sale.order', required=True, readonly=True)
    invoice_amount = fields.Monetary(string='Invoice Amount', required=True)
    currency_id = fields.Many2one(related='sale_order_id.currency_id', readonly=True)

    def create_partial_invoice(self):
        self.ensure_one()
        order = self.sale_order_id

        if order.approval_state != 'approved':
            raise ValidationError("Invoice can only be created when the Sale Order is in 'Approved' state.")

        already_invoiced = sum(order.invoice_ids.filtered(lambda inv: inv.state != 'cancel').mapped('amount_untaxed'))
        remaining_amount = order.amount_untaxed - already_invoiced

        if self.invoice_amount > remaining_amount:
            raise ValidationError(f"Invoice amount exceeds the remaining uninvoiced amount ({remaining_amount:.2f})")

        # Use first order line as reference (optional — depends on your use case)
        sale_line = order.order_line[:1]

        # Determine income account
        income_account = sale_line.product_id.property_account_income_id or \
                        sale_line.product_id.categ_id.property_account_income_categ_id

        if not income_account:
            raise UserError("No income account defined on the product or its category.")

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': order.partner_invoice_id.id,
            'invoice_origin': order.name,
            'invoice_user_id': order.user_id.id,
            'currency_id': order.currency_id.id,
            'invoice_payment_term_id': order.payment_term_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': f'Invoice for {order.name}',
                'quantity': 1,
                'price_unit': self.invoice_amount,
                'account_id': income_account.id,
                'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
                'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
            })],
            'invoice_date': fields.Date.today(),
        }

        invoice = self.env['account.move'].create(invoice_vals)

        # ✅ Link the invoice to the sale.order (inverse is automatic via `sale_line_ids`)
        order.invoice_ids = [(4, invoice.id)]

        # Do NOT post (stays in 'draft')
        return {
            'name': 'Customer Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
            'target': 'current'
        }
