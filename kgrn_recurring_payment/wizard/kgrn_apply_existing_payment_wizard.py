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
    payment_id = fields.Many2one(
        'account.payment',
        string='Existing Payment',
        required=True,
        domain="[('partner_id', 'child_of', partner_id), "
               "('state', '=', 'posted'), "
               "('payment_type', '=', 'inbound'), "
               "('currency_id', '=', currency_id)]",
        help='Select a posted payment to reconcile with this invoice.',
    )
    payment_amount = fields.Monetary(
        related='payment_id.amount',
        string='Payment Amount',
        currency_field='currency_id',
        readonly=True,
    )
    payment_memo = fields.Char(
        related='payment_id.memo',
        string='Payment Memo',
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

        # Receivable line from invoice (debit, unreconciled)
        inv_lines = invoice.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
        )
        # Receivable line from payment (credit, unreconciled)
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

        # Reconcile — Odoo matches the debit/credit and marks lines reconciled
        (inv_lines | pay_lines).reconcile()

        # Post a note on the invoice chatter
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
