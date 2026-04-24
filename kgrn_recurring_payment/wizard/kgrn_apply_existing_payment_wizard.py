from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KgrnApplyExistingPaymentWizard(models.TransientModel):
    _name = 'kgrn.apply.existing.payment.wizard'
    _description = 'Apply Existing Payment to Invoice'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related='move_id.partner_id',
        string='Customer',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='move_id.currency_id',
        string='Currency',
        readonly=True,
    )
    invoice_amount = fields.Monetary(
        related='move_id.amount_total',
        string='Invoice Total',
        currency_field='currency_id',
        readonly=True,
    )
    amount_residual = fields.Monetary(
        related='move_id.amount_residual',
        string='Outstanding Amount',
        currency_field='currency_id',
        readonly=True,
    )

    # Payments from the sale order linked to this invoice
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Linked Sale Order',
        compute='_compute_sale_order_id',
        readonly=True,
    )
    available_payment_ids = fields.Many2many(
        'account.payment',
        string='Available Payments',
        compute='_compute_available_payment_ids',
    )

    payment_id = fields.Many2one(
        'account.payment',
        string='Payment to Apply',
        required=True,
        domain="[('id', 'in', available_payment_ids)]",
        help='Payments already collected against the linked sale order.',
    )
    payment_amount = fields.Monetary(
        related='payment_id.amount',
        string='Payment Amount',
        currency_field='currency_id',
        readonly=True,
    )
    payment_memo = fields.Char(
        related='payment_id.memo',
        string='Payment Reference',
        readonly=True,
    )
    payment_date = fields.Date(
        related='payment_id.date',
        string='Payment Date',
        readonly=True,
    )
    amount_to_reconcile = fields.Monetary(
        string='Amount to Reconcile',
        currency_field='currency_id',
        compute='_compute_amount_to_reconcile',
        readonly=True,
    )

    @api.depends('move_id')
    def _compute_sale_order_id(self):
        for rec in self:
            sale = rec.move_id.invoice_line_ids.sale_line_ids.order_id[:1]
            rec.sale_order_id = sale

    @api.depends('sale_order_id', 'move_id')
    def _compute_available_payment_ids(self):
        for rec in self:
            if rec.sale_order_id:
                # Payments linked to the sale order that are still posted and have
                # unreconciled receivable lines
                payments = rec.sale_order_id.kgrn_account_payment_ids.filtered(
                    lambda p: p.state == 'posted'
                    and any(
                        not l.reconciled
                        for l in p.line_ids
                        if l.account_id.account_type == 'asset_receivable'
                    )
                )
            else:
                # Fallback: all posted inbound payments for this partner + currency
                payments = self.env['account.payment'].search([
                    ('partner_id', 'child_of', rec.move_id.partner_id.id),
                    ('state', '=', 'posted'),
                    ('payment_type', '=', 'inbound'),
                    ('currency_id', '=', rec.move_id.currency_id.id),
                ])
            rec.available_payment_ids = payments

    @api.depends('payment_id', 'move_id')
    def _compute_amount_to_reconcile(self):
        for rec in self:
            if not rec.payment_id or not rec.move_id:
                rec.amount_to_reconcile = 0.0
                continue
            pay_residual = abs(sum(
                rec.payment_id.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable'
                              and not l.reconciled
                ).mapped('amount_residual')
            ))
            rec.amount_to_reconcile = min(rec.move_id.amount_residual, pay_residual)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = res.get('move_id') or self.env.context.get('default_move_id')
        if not move_id:
            return res
        move = self.env['account.move'].browse(move_id)
        sale = move.invoice_line_ids.sale_line_ids.order_id[:1]
        if sale:
            payments = sale.kgrn_account_payment_ids.filtered(
                lambda p: p.state == 'posted'
                and any(
                    not l.reconciled
                    for l in p.line_ids
                    if l.account_id.account_type == 'asset_receivable'
                )
            )
            # Auto-select if only one unreconciled payment available
            if len(payments) == 1:
                res['payment_id'] = payments.id
        return res

    def action_apply(self):
        self.ensure_one()
        invoice = self.move_id
        payment = self.payment_id

        if invoice.payment_state == 'paid':
            raise UserError(_('This invoice is already fully paid.'))
        if invoice.state != 'posted':
            raise UserError(_('Only posted invoices can be reconciled.'))
        if payment.state != 'posted':
            raise UserError(_('Only posted payments can be applied.'))

        inv_lines = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
        )
        pay_lines = payment.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
        )

        if not inv_lines:
            raise UserError(_(
                'No unreconciled receivable entry found on invoice %s.\n'
                'It may already be fully reconciled.'
            ) % invoice.name)
        if not pay_lines:
            raise UserError(_(
                'No unreconciled receivable entry found on payment %s.\n'
                'This payment may already be fully applied to another invoice.'
            ) % payment.name)

        (inv_lines | pay_lines).reconcile()

        invoice.message_post(
            body=_('Payment <strong>%s</strong> (%s %s, dated %s) applied via Existing Payment reconciliation.')
            % (
                payment.name,
                self.currency_id.symbol or self.currency_id.name,
                f'{payment.amount:,.2f}',
                payment.date.strftime('%d %b %Y'),
            ),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
