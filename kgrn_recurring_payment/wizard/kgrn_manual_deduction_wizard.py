from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from odoo.addons.kgrn_recurring_payment.models.kgrn_recurring_contract import (
    FREQUENCY_DELTA,
    FREQUENCY_LABEL,
)


class KgrnManualDeductionWizard(models.TransientModel):
    """Wizard that lets the user review and confirm a manual payment deduction.

    Opens from the 'Manual Deduction' button on a running contract.
    Displays the billing period that will be charged and allows the user
    to adjust the journal before confirming.
    """

    _name = 'kgrn.manual.deduction.wizard'
    _description = 'KGRN Manual Payment Deduction'

    # ── Contract (read-only) ─────────────────────────────────────────────

    contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Contract',
        required=True,
        readonly=True,
    )
    contract_name = fields.Char(
        string='Contract Reference',
        related='contract_id.name',
        readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='contract_id.customer_id',
        readonly=True,
    )
    frequency_label = fields.Char(
        string='Billing Frequency',
        compute='_compute_period',
        readonly=True,
    )
    card_info = fields.Char(
        string='Registered Card',
        compute='_compute_card_info',
        readonly=True,
    )

    # ── Period being charged ─────────────────────────────────────────────

    period_start = fields.Date(
        string='Period Start',
        compute='_compute_period',
        store=False,
        readonly=True,
    )
    period_end = fields.Date(
        string='Period End',
        compute='_compute_period',
        store=False,
        readonly=True,
    )
    period_label = fields.Char(
        string='Billing Period',
        compute='_compute_period',
        readonly=True,
    )

    # ── Amount ───────────────────────────────────────────────────────────

    amount = fields.Monetary(
        string='Amount to Charge',
        related='contract_id.amount',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='contract_id.currency_id',
        readonly=True,
    )

    # ── Next payment after this deduction ────────────────────────────────

    next_payment_after = fields.Date(
        string='Next Payment Date After This Deduction',
        compute='_compute_period',
        readonly=True,
    )

    # ── Journal (editable) ───────────────────────────────────────────────

    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain=[('type', 'in', ['bank', 'cash'])],
    )

    # ── Computations ─────────────────────────────────────────────────────

    @api.depends('contract_id')
    def _compute_period(self):
        for rec in self:
            contract = rec.contract_id
            if not contract or not contract.frequency:
                rec.frequency_label = ''
                rec.period_start = False
                rec.period_end = False
                rec.period_label = ''
                rec.next_payment_after = False
                continue

            delta = FREQUENCY_DELTA[contract.frequency]
            p_start = contract.next_payment_date or fields.Date.today()
            p_end   = p_start + delta - timedelta(days=1)
            next_pd = p_start + delta

            rec.frequency_label   = FREQUENCY_LABEL[contract.frequency]
            rec.period_start      = p_start
            rec.period_end        = p_end
            rec.period_label      = (
                f'{p_start.strftime("%d %b %Y")} \u2013 {p_end.strftime("%d %b %Y")}'
            )
            rec.next_payment_after = next_pd

    @api.depends('contract_id')
    def _compute_card_info(self):
        for rec in self:
            c = rec.contract_id
            if c.card_brand and c.card_last4:
                rec.card_info = (
                    f'{c.card_brand} \u2022\u2022\u2022\u2022 {c.card_last4}'
                    + (f'  (exp {c.card_exp_month:02d}/{c.card_exp_year})' if c.card_exp_month else '')
                )
            else:
                rec.card_info = 'No card registered'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = self.env.context.get('default_contract_id')
        if contract_id:
            contract = self.env['kgrn.recurring.contract'].browse(contract_id)
            res['journal_id'] = (
                contract.journal_id.id
                or self.env['account.journal'].search(
                    [('type', 'in', ['bank', 'cash']),
                     ('company_id', '=', contract.company_id.id)],
                    limit=1,
                ).id
                or False
            )
        return res

    # ── Action ───────────────────────────────────────────────────────────

    def action_confirm_deduction(self):
        """Trigger payment deduction after user has reviewed the period."""
        self.ensure_one()
        contract = self.contract_id

        if contract.state != 'running':
            raise UserError(_('Contract is no longer in Running state.'))
        if not contract.stripe_payment_method_id:
            raise UserError(_('No payment card is registered on this contract.'))

        # Override journal if user changed it
        if self.journal_id and self.journal_id != contract.journal_id:
            contract.journal_id = self.journal_id

        contract._process_single_payment()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payment Processed'),
                'message': _(
                    'Manual deduction for period %s has been triggered. '
                    'Check the Payment History tab for the result.'
                ) % self.period_label,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
