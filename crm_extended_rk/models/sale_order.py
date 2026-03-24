from odoo import api, models, fields
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    reminder_date = fields.Date(string='Reminder Date')
    advance_amount = fields.Float(string='Advance Amount', default=0.00)
    auto_invoice = fields.Boolean(string="Auto Invoice", default=True)

    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')
    pending_amount = fields.Monetary(string='Pending Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')

    order_status = fields.Selection(
        [
            ('new', 'New'),
            ('opened', 'Opened'),
            ('closed', 'Closed'),
        ],
        string='Order Status',
        default='new',
        required=True,
    )

    def action_open_invoice_wizard(self):
        return {
            'name': 'Create Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            }
        }

    @api.depends('invoice_ids.payment_state', 'amount_total')
    def _compute_paid_pending(self):
        for order in self:
            paid = 0.0
            # Calculate paid amount from invoices
            invoices = order.invoice_ids.filtered(lambda inv: inv.state in ['posted', 'paid'])
            for inv in invoices:
                # inv.amount_residual is unpaid amount, so paid is total - residual
                paid += inv.amount_total - inv.amount_residual

            order.paid_amount = paid
            order.pending_amount = order.amount_total - paid

    def action_confirm(self):
        res = super().action_confirm()
        # for order in self:
        #     if order.advance_amount > 0.0:
        #         order._create_advance_invoice()
        return res

    # def _create_advance_invoice(self):
    #     self.ensure_one()

    #     if not self.partner_invoice_id:
    #         raise UserError("Please set an invoice address for the customer.")

    #     existing_invoice = self.invoice_ids.filtered(
    #         lambda inv: inv.state == 'draft' and
    #                     inv.amount_total == self.advance_amount and
    #                     inv.invoice_origin == self.name
    #     )
    #     if existing_invoice:
    #         return

    #     income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
    #     if not income_account:
    #         raise UserError("No income account found for advance invoice line.")

    #     # Optionally reference the first order line (if you want to link it)
    #     sale_line = self.order_line[:1]  # You can also create a fake "advance" line if needed

    #     invoice_vals = {
    #         'move_type': 'out_invoice',
    #         'partner_id': self.partner_invoice_id.id,
    #         'invoice_origin': self.name,
    #         'invoice_user_id': self.user_id.id,
    #         'currency_id': self.currency_id.id,
    #         'invoice_payment_term_id': self.payment_term_id.id,
    #         'invoice_line_ids': [(0, 0, {
    #             'name': 'Advance Payment',
    #             'quantity': 1,
    #             'price_unit': self.advance_amount,
    #             'account_id': income_account.id,
    #             'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
    #             # ✅ Link to Sale Order Line (for reporting)
    #             'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
    #         })],
    #     }

    #     invoice = self.env['account.move'].create(invoice_vals)
    #     return invoice


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    engagement_start = fields.Date(string='Engagement Start', required=True)
    engagement_end = fields.Date(string='Engagement End', required=True)
    manager_id = fields.Many2one('res.users', string='Manager', required=True)
    deadline = fields.Date(string='Deadline', required=True)
    estimated_hours = fields.Float(string='Estimated Number of Hours', required=True)

    @api.onchange('product_id')
    def _onchange_product_id_fetch_estimated_hours(self):
        if self.product_id:
            self.estimated_hours = self.product_id.product_tmpl_id.estimated_hours  # get from product template

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    estimated_hours = fields.Float(string='Estimated Hours')

class ProjectProject(models.Model):
    _inherit = 'project.project'

    estimated_hours = fields.Float(string='Estimated Hours')
