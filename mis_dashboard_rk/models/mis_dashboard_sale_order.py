from odoo import models, fields, api
from odoo.tools.float_utils import float_compare

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    manager_id = fields.Many2one(
        'res.users',
        string='Project Manager'
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='manager_id.employee_ids.department_id',
        store=True
    )

    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices',
        compute='_compute_invoice_ids',
    )

    outstanding_amount = fields.Monetary(
        string='Outstanding',
        compute='_compute_outstanding',
        store=False,
        currency_field='currency_id'
    )
    
    is_fully_delivered = fields.Boolean(
        string='Fully Delivered',
        compute='_compute_is_fully_delivered',
        store=True,
        index=True
    )

    task_value = fields.Monetary(
        string='Task Value',
        compute='_compute_task_value',
        store=False,
        currency_field='currency_id'
    )

    invoice_status_custom = fields.Selection(
        [('paid', 'Paid'), ('not_paid', 'Not Paid'), ('no_invoice', 'No Invoices Raised')],
        string='Invoice Status',
        compute='_compute_invoice_status',
        store=False
    )

    advance_per_line = fields.Monetary(
        string='Advance Amount',
        compute='_compute_advance_per_line',
        store=False,
        currency_field='currency_id'
    )

    order_date = fields.Datetime(
        string='Order Date',
        related='order_id.create_date',
        store=True
    )

    invoice_date_min = fields.Datetime(
        string='Invoice Date',
        compute='_compute_invoice_date',
        store=True
    )

    @api.depends('invoice_ids.invoice_date')
    def _compute_invoice_date(self):
        for line in self:
            if line.invoice_ids:
                line.invoice_date_min = min(line.invoice_ids.mapped('invoice_date'))
            else:
                line.invoice_date_min = False

    @api.depends('invoice_ids', 'invoice_ids.payment_state', 'create_date')
    def _compute_invoice_status(self):
        for line in self:
            if not line.invoice_ids:
                line.invoice_status_custom = 'no_invoice'
            elif all(inv.payment_state == 'paid' for inv in line.invoice_ids):
                line.invoice_status_custom = 'paid'
            else:
                line.invoice_status_custom = 'not_paid'

    @api.depends('product_uom_qty', 'qty_delivered', 'product_uom.rounding')
    def _compute_is_fully_delivered(self):
        for line in self:
            rounding = line.product_uom.rounding or 0.01
            if line.qty_delivered >= line.product_uom_qty:
                # Fully delivered
                line.is_fully_delivered = True
            elif line.qty_delivered > 0:
                # Partially delivered / in progress
                line.is_fully_delivered = True  # You could add another field for "in progress"
            else:
                # Not delivered at all
                line.is_fully_delivered = False

    @api.depends('price_subtotal', 'order_id.advance_amount', 'order_id.order_line')
    def _compute_task_value(self):
        for line in self:
            total_lines = len(line.order_id.order_line)
            if total_lines > 0:
                line.task_value = line.price_subtotal - (line.order_id.advance_amount / total_lines)
            else:
                line.task_value = line.price_subtotal

    @api.depends()
    def _compute_invoice_ids(self):
        for line in self:
            # Only include posted invoices
            invoices = self.env['account.move'].search([
                ('invoice_line_ids.sale_line_ids', 'in', line.id),
                ('state', '=', 'posted'),
            ])
            line.invoice_ids = invoices

    @api.depends('invoice_ids', 'qty_delivered', 'product_uom_qty', 'price_subtotal', 'advance_per_line', 'task_value')
    def _compute_outstanding(self):
        for line in self:
            # Sum of invoice lines linked to this sale order line where invoice is not paid
            total_unpaid = 0.0
            for invoice in line.invoice_ids.filtered(lambda i: i.payment_state != 'paid'):
                for inv_line in invoice.invoice_line_ids:
                    if line in inv_line.sale_line_ids:
                        total_unpaid += inv_line.price_unit

            # Outstanding = sum of unpaid invoice lines
            line.outstanding_amount = max(total_unpaid, 0.0)

        
    @api.depends('invoice_ids.advance_invoice', 'invoice_ids.invoice_line_ids', 'order_id.advance_amount')
    def _compute_advance_per_line(self):
        for line in self:
            # Find invoice with advance_invoice=True
            advance_invoice = line.invoice_ids.filtered(lambda inv: inv.advance_invoice)
            if advance_invoice:
                # Take the sum of price_unit from invoice lines related to this sale order line
                advance_amount = sum(
                    inv_line.price_unit
                    for inv in advance_invoice
                    for inv_line in inv.invoice_line_ids
                    if line in inv_line.sale_line_ids
                )
                line.advance_per_line = advance_amount
            else:
                # Fallback: set to 0 if no advance invoice
                line.advance_per_line = 0.0
        

class AccountMove(models.Model):
    _inherit = 'account.move'

    sale_line_price_unit = fields.Float(
        string='Unit Price',
        compute='_compute_sale_line_price_unit',
        store=False
    )

    advance_invoice = fields.Boolean(string='Advance Invoice')

    advance_invoice_status = fields.Selection(
        [('advance', 'Advance Invoice'), ('not_advance', 'Sales Invoice')],
        string='Advance Status',
        compute='_compute_advance_invoice_status',
        store=True
    )

    def _compute_sale_line_price_unit(self):
        for inv in self:
            # Sum all price_unit from invoice lines related to sale order lines
            units = []
            for line in inv.invoice_line_ids:
                units.append(line.price_unit)

            inv.sale_line_price_unit = units[0] if units else 0.0

    @api.depends('advance_invoice')
    def _compute_advance_invoice_status(self):
        for move in self:
            if move.advance_invoice:
                move.advance_invoice_status = 'advance'
            else:
                move.advance_invoice_status = 'not_advance'
