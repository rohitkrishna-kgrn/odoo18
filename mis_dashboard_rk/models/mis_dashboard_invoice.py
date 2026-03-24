from odoo import models, fields, api, _

class AccountMove(models.Model):
    _inherit = 'account.move'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        compute='_compute_sale_order_line',
        store=True
    )

    invoice_group_key = fields.Char(
        string="Invoice Group Key",
        compute="_compute_invoice_group_key",
        store=True,
    )

    manager_department_id = fields.Many2one(
        'hr.department',
        string="Manager Department",
        compute="_compute_manager_data",
        store=True
    )

    manager_id_from_sol = fields.Many2one(
        'res.users',
        string="Manager",
        compute="_compute_manager_data",
        store=True
    )

    # New fields
    line_status = fields.Char(
        string="Project Status",
        compute="_compute_line_status",
        store=True
    )

    sale_order_name = fields.Char(
        string="Sale Order",
        compute="_compute_line_status",
        store=True
    )

    invoice_amount = fields.Float(
        string="Invoice Amount",
        compute="_compute_invoice_amounts",
        store=True
    )

    invoice_outstanding = fields.Float(
        string="Outstanding Amount",
        compute="_compute_invoice_amounts",
        store=True
    )

    line_subtotal = fields.Float(
        string="Line Subtotal",
        compute="_compute_line_status",
        store=True
    )

    sale_order_advance_amount = fields.Float(
        string="Advance Amount",
        compute="_compute_line_status",
        store=True
    )

    sale_order_total_amount = fields.Float(
        string="Total Sale Order Amount",
        compute="_compute_line_status",
        store=True
    )

    @api.depends('sale_order_total_amount')
    def _compute_total_pending_amount(self):
        """
        total_pending_amount = sale_order_total_amount - (sum of all paid invoices of the sale order)
        """
        for inv in self:
            sale_total = inv.sale_order_total_amount or 0

            paid_amount_sum = 0

            # Ensure invoice is linked to a sale order
            if inv.invoice_line_ids.mapped('sale_line_ids.order_id'):
                sale_order = inv.invoice_line_ids.mapped('sale_line_ids.order_id')[0]

                # Get all invoices created from this sale order
                invoices = sale_order.invoice_ids.filtered(lambda x: x.state == 'posted')

                # Sum PAID amounts = (total - residual) for each invoice
                paid_amount_sum = sum(
                    (i.amount_total or 0) - (i.amount_residual or 0)
                    for i in invoices
                )

            inv.total_pending_amount = sale_total - paid_amount_sum


    @api.depends("sale_order_line_id", "sale_order_line_id.manager_id")
    def _compute_invoice_group_key(self):
        for move in self:
            if move.sale_order_line_id and move.sale_order_line_id.manager_id:
                move.invoice_group_key = move.sale_order_line_id.manager_id.name
            else:
                move.invoice_group_key = "KGRN"

    @api.depends('invoice_line_ids.sale_line_ids')
    def _compute_sale_order_line(self):
        for move in self:
            sale_lines = move.invoice_line_ids.mapped('sale_line_ids')
            move.sale_order_line_id = sale_lines[:1] if sale_lines else False

    @api.depends("sale_order_line_id",
                 "sale_order_line_id.manager_id",
                 "sale_order_line_id.manager_id.department_id")
    def _compute_manager_data(self):
        for move in self:
            sol = move.sale_order_line_id
            if sol and sol.manager_id:
                move.manager_id_from_sol = sol.manager_id
                move.manager_department_id = sol.manager_id.department_id
                move.invoice_group_key = "HasSaleLine"
            else:
                move.manager_id_from_sol = False
                move.manager_department_id = False
                move.invoice_group_key = "KGRN"

    @api.depends('sale_order_line_id')
    def _compute_line_status(self):
        for move in self:
            sol = move.sale_order_line_id
            if sol:

                move.sale_order_name = sol.order_id.name
                # Status based on qty delivered
                move.line_status = 'Completed' if sol.product_uom_qty == sol.qty_delivered else 'In Progress'
                
                # Total line subtotal
                move.line_subtotal = sum(line.price_subtotal for line in sol.order_id.order_line)
                
                # Sale order advance amount
                move.sale_order_advance_amount = sol.order_id.advance_amount
                
                # Total sale order value
                move.sale_order_total_amount = sol.order_id.amount_total
            else:
                move.line_status = 'No Sale Line'
                move.line_subtotal = 0.0
                move.sale_order_advance_amount = 0.0
                move.sale_order_total_amount = 0.0

    @api.depends('amount_total', 'amount_residual', 'state')
    def _compute_invoice_amounts(self):
        for move in self:

            # Reset
            move.invoice_amount = 0.0
            move.invoice_outstanding = 0.0

            if move.state != "posted":
                continue

            # Always show invoice total — advance is NOT separated
            move.invoice_amount = move.amount_total

            # Outstanding = Odoo residual
            residual = move.amount_residual

            if residual <= 0:
                move.invoice_outstanding = 0.0
            else:
                move.invoice_outstanding = residual
