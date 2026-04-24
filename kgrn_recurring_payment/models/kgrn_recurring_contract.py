import uuid
import hmac
import hashlib
import logging
import requests
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stripe API helper (pure-requests, no stripe package required)
# ---------------------------------------------------------------------------

class _StripeAPI:
    """Thin wrapper around the Stripe REST API using the requests library."""

    BASE = 'https://api.stripe.com/v1'

    def __init__(self, secret_key):
        self._key = secret_key

    # -- low-level ----------------------------------------------------------

    def _post(self, path, **kwargs):
        resp = requests.post(
            f'{self.BASE}{path}',
            auth=(self._key, ''),
            data=self._flatten(kwargs),
            timeout=30,
        )
        return resp.json()

    def _get(self, path, **params):
        resp = requests.get(
            f'{self.BASE}{path}',
            auth=(self._key, ''),
            params=params,
            timeout=30,
        )
        return resp.json()

    @staticmethod
    def _flatten(d, prefix=''):
        """Flatten nested dict to Stripe-style form-encoded keys."""
        result = {}
        for k, v in d.items():
            key = f'{prefix}[{k}]' if prefix else k
            if isinstance(v, dict):
                result.update(_StripeAPI._flatten(v, prefix=key))
            elif isinstance(v, (list, tuple)):
                for item in v:
                    result[f'{key}[]'] = item
            elif v is not None:
                result[key] = v
        return result

    # -- customer -----------------------------------------------------------

    def create_customer(self, name, email, contract_ref):
        return self._post(
            '/customers',
            name=name,
            email=email,
            metadata={'contract_ref': contract_ref},
        )

    # -- setup intent (save card without charging) --------------------------

    def create_setup_intent(self, customer_id, contract_ref):
        return self._post(
            '/setup_intents',
            customer=customer_id,
            usage='off_session',
            metadata={'contract_ref': contract_ref},
            **{'payment_method_types[]': 'card'},
        )

    # -- payment method -----------------------------------------------------

    def get_payment_method(self, pm_id):
        return self._get(f'/payment_methods/{pm_id}')

    def attach_payment_method(self, pm_id, customer_id):
        return self._post(f'/payment_methods/{pm_id}/attach', customer=customer_id)

    def detach_payment_method(self, pm_id):
        return self._post(f'/payment_methods/{pm_id}/detach')

    # -- payment intent (off-session charge) --------------------------------

    def create_payment_intent(self, amount_cents, currency, customer_id, pm_id,
                              description, contract_ref, period_label):
        return self._post(
            '/payment_intents',
            amount=str(int(amount_cents)),
            currency=currency.lower(),
            customer=customer_id,
            payment_method=pm_id,
            confirm='true',
            off_session='true',
            description=description,
            metadata={
                'contract_ref': contract_ref,
                'period': period_label,
            },
        )

    # -- webhook verification -----------------------------------------------

    @staticmethod
    def verify_webhook(raw_body: bytes, sig_header: str, secret: str) -> bool:
        try:
            parts = {p.split('=')[0]: p.split('=')[1]
                     for p in sig_header.split(',') if '=' in p}
            timestamp = parts.get('t', '')
            signature = parts.get('v1', '')
            signed = f'{timestamp}.{raw_body.decode("utf-8")}'
            expected = hmac.new(
                secret.encode('utf-8'),
                signed.encode('utf-8'),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------

FREQUENCY_DELTA = {
    'daily': relativedelta(days=1),
    'weekly': relativedelta(weeks=1),
    'monthly': relativedelta(months=1),
    'quarterly': relativedelta(months=3),
    'half_yearly': relativedelta(months=6),
    'yearly': relativedelta(years=1),
}

FREQUENCY_LABEL = {
    'daily': 'Daily',
    'weekly': 'Weekly',
    'monthly': 'Monthly',
    'quarterly': 'Quarterly',
    'half_yearly': 'Half-Yearly',
    'yearly': 'Yearly',
}


class KgrnRecurringContract(models.Model):
    _name = 'kgrn.recurring.contract'
    _description = 'KGRN Recurring Payment Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    # -----------------------------------------------------------------------
    # Identity
    # -----------------------------------------------------------------------

    name = fields.Char(
        string='Contract Reference',
        readonly=True,
        default='New',
        copy=False,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
    )

    # -----------------------------------------------------------------------
    # Customer details
    # -----------------------------------------------------------------------

    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        tracking=True,
        domain=[('is_company', '=', False)],
    )
    customer_email = fields.Char(
        string='Customer Email',
        related='customer_id.email',
        store=True,
    )
    customer_phone = fields.Char(
        string='Customer Phone',
        related='customer_id.phone',
        store=True,
    )

    # -----------------------------------------------------------------------
    # Billing
    # -----------------------------------------------------------------------

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount = fields.Monetary(
        string='Recurring Amount',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    frequency = fields.Selection(
        selection=[
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
            ('half_yearly', 'Half-Yearly'),
            ('yearly', 'Yearly'),
        ],
        string='Billing Frequency',
        required=True,
        default='monthly',
        tracking=True,
    )
    start_date = fields.Date(
        string='Start Date',
        required=True,
        tracking=True,
    )
    end_date = fields.Date(
        string='End Date',
        required=True,
        tracking=True,
    )
    next_payment_date = fields.Date(
        string='Next Payment Date',
        readonly=True,
        tracking=True,
    )

    # -----------------------------------------------------------------------
    # Sale order link
    # -----------------------------------------------------------------------

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sale Order',
        copy=False,
        ondelete='set null',
        tracking=True,
        help='Sale order this recurring contract was created from.',
    )

    # -----------------------------------------------------------------------
    # Accounting
    # -----------------------------------------------------------------------

    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain=[('type', 'in', ['bank', 'cash'])],
        help='Journal used to post recurring payment entries.',
    )
    tax_ids = fields.Many2many(
        'account.tax',
        'kgrn_recurring_contract_tax_rel',
        'contract_id',
        'tax_id',
        string='Default Tax',
        domain=[('type_tax_use', '=', 'sale')],
        help='Tax shown on payment receipts for reference.',
    )
    advance_amount = fields.Monetary(
        string='Advance Amount',
        currency_field='currency_id',
        help='One-time advance to collect before recurring billing. Auto-fetched from the linked sale order.',
    )
    kgrn_advance_paid = fields.Boolean(
        string='Advance Collected',
        default=False,
        copy=False,
        tracking=True,
    )

    # -----------------------------------------------------------------------
    # Stripe
    # -----------------------------------------------------------------------

    stripe_provider_id = fields.Many2one(
        'payment.provider',
        string='Stripe Provider',
        domain=[('code', '=', 'stripe')],
        required=True,
        help='Select the Stripe payment provider to use for card collection and charging.',
    )
    stripe_customer_id = fields.Char(
        string='Stripe Customer ID',
        readonly=True,
        copy=False,
    )
    stripe_payment_method_id = fields.Char(
        string='Stripe Payment Method ID',
        readonly=True,
        copy=False,
    )

    # -----------------------------------------------------------------------
    # Card info (populated after customer adds card)
    # -----------------------------------------------------------------------

    card_brand = fields.Char(string='Card Brand', readonly=True, copy=False)
    card_last4 = fields.Char(string='Card Last 4 Digits', readonly=True, copy=False)
    card_exp_month = fields.Integer(string='Card Expiry Month', readonly=True, copy=False)
    card_exp_year = fields.Integer(string='Card Expiry Year', readonly=True, copy=False)
    card_added_date = fields.Datetime(string='Card Added On', readonly=True, copy=False)
    card_holder_name = fields.Char(string='Cardholder Name', readonly=True, copy=False)

    # -----------------------------------------------------------------------
    # Card removal workflow (customer-side request)
    # -----------------------------------------------------------------------

    card_removal_requested = fields.Boolean(
        string='Card Removal Requested',
        readonly=True,
        copy=False,
        tracking=True,
    )
    card_removal_reason = fields.Text(
        string='Removal Request Reason',
        readonly=True,
        copy=False,
    )
    card_removal_request_date = fields.Datetime(
        string='Removal Requested On',
        readonly=True,
        copy=False,
    )

    # -----------------------------------------------------------------------
    # Portal
    # -----------------------------------------------------------------------

    access_token = fields.Char(
        string='Portal Access Token',
        readonly=True,
        copy=False,
        index=True,
    )
    portal_url = fields.Char(
        string='Customer Portal URL',
        compute='_compute_portal_url',
        store=False,
    )
    portal_link_sent = fields.Boolean(
        string='Portal Link Sent',
        readonly=True,
        copy=False,
    )
    portal_link_sent_date = fields.Datetime(
        string='Link Sent On',
        readonly=True,
        copy=False,
    )

    # -----------------------------------------------------------------------
    # State
    # -----------------------------------------------------------------------

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        readonly=True,
        tracking=True,
        copy=False,
    )

    # -----------------------------------------------------------------------
    # Relations
    # -----------------------------------------------------------------------

    payment_line_ids = fields.One2many(
        'kgrn.recurring.payment.line',
        'contract_id',
        string='Payment History',
    )
    payment_count = fields.Integer(
        string='Payments',
        compute='_compute_payment_count',
    )
    notes = fields.Text(string='Internal Notes')

    # -----------------------------------------------------------------------
    # Computed helpers
    # -----------------------------------------------------------------------

    @api.depends('access_token')
    def _compute_portal_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.access_token:
                rec.portal_url = f'{base}/kgrn/recurring/card/{rec.access_token}'
            else:
                rec.portal_url = False

    @api.depends('payment_line_ids')
    def _compute_payment_count(self):
        for rec in self:
            rec.payment_count = len(rec.payment_line_ids)

    def _get_frequency_label(self):
        return FREQUENCY_LABEL.get(self.frequency, self.frequency)

    # -----------------------------------------------------------------------
    # Constraints
    # -----------------------------------------------------------------------

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.end_date and rec.start_date and rec.end_date <= rec.start_date:
                raise ValidationError(_('End Date must be after Start Date.'))

    @api.constrains('start_date')
    def _check_start_date_not_past(self):
        today = fields.Date.today()
        for rec in self:
            if rec.state == 'draft' and rec.start_date and rec.start_date < today:
                raise ValidationError(_(
                    'Start Date cannot be in the past. '
                    'Please select today or a future date.'
                ))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Recurring Amount must be greater than zero.'))

    # -----------------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------------

    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id and not self.advance_amount:
            so = self.sale_order_id
            if 'advance_amount' in so._fields and so.advance_amount:
                self.advance_amount = so.advance_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('kgrn.recurring.contract') or 'New'
            if not vals.get('access_token'):
                vals['access_token'] = uuid.uuid4().hex
            # Auto-fetch advance_amount from the linked sale order on creation
            if vals.get('sale_order_id') and not vals.get('advance_amount'):
                so = self.env['sale.order'].browse(vals['sale_order_id'])
                if 'advance_amount' in so._fields and so.advance_amount:
                    vals['advance_amount'] = so.advance_amount
        records = super().create(vals_list)
        # Sync back to sale order: set kgrn_recurring_contract_id on the sale order
        for rec in records:
            if rec.sale_order_id and not rec.sale_order_id.kgrn_recurring_contract_id:
                rec.sale_order_id.sudo().kgrn_recurring_contract_id = rec.id
        return records

    # -----------------------------------------------------------------------
    # State transitions
    # -----------------------------------------------------------------------

    def action_activate(self):
        """Manually activate a draft contract (internal user)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft contracts can be activated.'))
            if not rec.stripe_payment_method_id:
                raise UserError(_(
                    'The customer has not yet added a payment card.\n'
                    'Please send them the portal link and wait for card registration.'
                ))
            rec._do_activate()

    def _do_activate(self):
        """Internal: move to Running and set next_payment_date."""
        self.ensure_one()
        today = fields.Date.today()
        next_date = self.start_date if self.start_date >= today else today
        self.write({
            'state': 'running',
            'next_payment_date': next_date,
        })
        self.message_post(
            body=_('Contract activated. First payment scheduled for %s.') % next_date,
        )

    def action_cancel(self):
        for rec in self:
            if rec.state in ('expired', 'cancelled'):
                raise UserError(_('This contract is already closed.'))
            rec.write({'state': 'cancelled'})
            rec.message_post(body=_('Contract cancelled by %s.') % rec.env.user.name)

    def action_mark_expired(self):
        for rec in self:
            if rec.state != 'running':
                raise UserError(_('Only running contracts can be marked as expired.'))
            rec.write({'state': 'expired'})
            rec.message_post(body=_('Contract marked as expired.'))

    def action_manual_deduct(self):
        """Open the manual deduction wizard for period confirmation."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_('Manual deduction is only available for Running contracts.'))
        if not self.stripe_payment_method_id:
            raise UserError(_('No payment card is registered on this contract.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manual Payment Deduction'),
            'res_model': 'kgrn.manual.deduction.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    # -----------------------------------------------------------------------
    # Portal link
    # -----------------------------------------------------------------------

    def action_send_portal_link(self):
        """Open the Send Portal Link wizard."""
        self.ensure_one()
        if not self.access_token:
            self.access_token = uuid.uuid4().hex
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send Payment Portal Link'),
            'res_model': 'kgrn.send.portal.link.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_recipient_email': self.customer_email or '',
            },
        }

    # -----------------------------------------------------------------------
    # Card removal (internal)
    # -----------------------------------------------------------------------

    def action_remove_card(self):
        """Internal: open the card removal action wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remove Payment Card'),
            'res_model': 'kgrn.card.removal.action.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def _detach_stripe_card(self, cancel_contract=False):
        """Detach the payment method from Stripe and clear local card data."""
        self.ensure_one()
        if self.stripe_payment_method_id:
            try:
                api = self._get_stripe_api()
                result = api.detach_payment_method(self.stripe_payment_method_id)
                if result.get('error'):
                    _logger.warning('Stripe detach error: %s', result['error'])
            except Exception as e:
                _logger.error('Failed to detach Stripe PM: %s', e)
        vals = {
            'stripe_payment_method_id': False,
            'card_brand': False,
            'card_last4': False,
            'card_exp_month': 0,
            'card_exp_year': 0,
            'card_added_date': False,
            'card_holder_name': False,
            'card_removal_requested': False,
            'card_removal_reason': False,
            'card_removal_request_date': False,
        }
        if cancel_contract:
            vals['state'] = 'cancelled'
        self.write(vals)
        self.message_post(body=_('Payment card removed by %s.') % self.env.user.name)

    # -----------------------------------------------------------------------
    # Stripe helpers
    # -----------------------------------------------------------------------

    def _get_stripe_api(self):
        self.ensure_one()
        provider = self.stripe_provider_id
        if not provider:
            raise UserError(_('No Stripe provider configured for this contract.'))
        secret_key = getattr(provider, 'stripe_secret_key', False)
        if not secret_key:
            raise UserError(_(
                'Stripe secret key is not configured on the selected payment provider.\n'
                'Please configure it under Accounting → Configuration → Payment Providers.'
            ))
        return _StripeAPI(secret_key)

    def _get_stripe_publishable_key(self):
        self.ensure_one()
        return getattr(self.stripe_provider_id, 'stripe_publishable_key', '') or ''

    def _ensure_stripe_customer(self):
        """Create a Stripe Customer if one does not exist yet."""
        self.ensure_one()
        if self.stripe_customer_id:
            return self.stripe_customer_id
        api = self._get_stripe_api()
        result = api.create_customer(
            name=self.customer_id.name,
            email=self.customer_email or '',
            contract_ref=self.name,
        )
        if result.get('error'):
            raise UserError(_('Stripe error creating customer: %s') % result['error']['message'])
        self.sudo().stripe_customer_id = result['id']
        return result['id']

    # -----------------------------------------------------------------------
    # Payment processing (called by cron)
    # -----------------------------------------------------------------------

    @api.model
    def _cron_process_recurring_payments(self):
        """Cron entry point: process all due payments."""
        today = fields.Date.today()
        contracts = self.search([
            ('state', '=', 'running'),
            ('next_payment_date', '<=', today),
        ])
        for contract in contracts:
            try:
                contract._process_single_payment()
            except Exception as e:
                _logger.error('Recurring payment failed for %s: %s', contract.name, e)

    @api.model
    def _cron_activate_scheduled_contracts(self):
        """Cron: activate contracts whose start_date has arrived."""
        today = fields.Date.today()
        contracts = self.search([
            ('state', '=', 'draft'),
            ('stripe_payment_method_id', '!=', False),
            ('start_date', '<=', today),
        ])
        for contract in contracts:
            try:
                contract._do_activate()
            except Exception as e:
                _logger.error('Auto-activate failed for %s: %s', contract.name, e)

    @api.model
    def _cron_expire_contracts(self):
        """Cron: expire running contracts whose end_date has passed."""
        today = fields.Date.today()
        contracts = self.search([
            ('state', '=', 'running'),
            ('end_date', '<', today),
        ])
        for contract in contracts:
            contract.write({'state': 'expired'})
            contract.message_post(body=_('Contract automatically expired (end date reached).'))

    def _process_single_payment(self):
        """Charge the customer card for the current period."""
        self.ensure_one()
        today = fields.Date.today()

        # Safety: if past end_date, expire instead of charging
        if self.next_payment_date and self.next_payment_date > self.end_date:
            self.write({'state': 'expired'})
            self.message_post(body=_('Contract expired — all billing periods completed.'))
            return

        period_start = self.next_payment_date or today
        delta = FREQUENCY_DELTA[self.frequency]
        period_end = period_start + delta - timedelta(days=1)
        period_label = f'{period_start.strftime("%d %b %Y")} – {period_end.strftime("%d %b %Y")}'

        # Create a pending payment line first (idempotency guard)
        line = self.env['kgrn.recurring.payment.line'].create({
            'contract_id': self.id,
            'name': f'{self.name} / {period_label}',
            'period_start': period_start,
            'period_end': period_end,
            'payment_date': today,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'state': 'pending',
        })

        try:
            api = self._get_stripe_api()
            amount_cents = int(self.amount * (10 ** self.currency_id.decimal_places))
            description = (
                f'KGRN Recurring – {self.name} – '
                f'{FREQUENCY_LABEL[self.frequency]} – {period_label}'
            )
            result = api.create_payment_intent(
                amount_cents=amount_cents,
                currency=self.currency_id.name,
                customer_id=self.stripe_customer_id,
                pm_id=self.stripe_payment_method_id,
                description=description,
                contract_ref=self.name,
                period_label=period_label,
            )

            if result.get('error'):
                error_msg = result['error'].get('message', 'Unknown Stripe error')
                line.write({
                    'state': 'failed',
                    'failure_reason': error_msg,
                    'stripe_payment_intent_id': result.get('error', {}).get('payment_intent', {}).get('id'),
                })
                self.message_post(
                    body=_(
                        'Payment FAILED for period %s.\nStripe error: %s'
                    ) % (period_label, error_msg),
                    subtype_xmlid='mail.mt_note',
                )
                # Notify responsible user
                self._notify_payment_failure(period_label, error_msg)
                return

            intent_status = result.get('status')
            pi_id = result.get('id')

            if intent_status in ('succeeded', 'processing'):
                # Create Odoo accounting payment
                account_payment = self._create_account_payment(period_label, today)
                line.write({
                    'state': 'success',
                    'stripe_payment_intent_id': pi_id,
                    'account_payment_id': account_payment.id if account_payment else False,
                    'processed_by': self.env.user.id,
                })
                # Advance next payment date
                next_date = period_start + delta
                if next_date > self.end_date:
                    self.write({'state': 'expired', 'next_payment_date': next_date})
                    self.message_post(body=_(
                        'Final payment collected for period %s. Contract expired.'
                    ) % period_label)
                else:
                    self.write({'next_payment_date': next_date})
                    self.message_post(body=_(
                        'Payment of %s %s collected for period %s. Next payment: %s.'
                    ) % (self.amount, self.currency_id.name, period_label, next_date))

                self._send_payment_receipt_email(line)

            elif intent_status == 'requires_action':
                line.write({
                    'state': 'failed',
                    'stripe_payment_intent_id': pi_id,
                    'failure_reason': 'Customer authentication required (3D Secure). Manual action needed.',
                })
                self.message_post(body=_(
                    'Payment for period %s requires customer authentication (3D Secure). '
                    'Please contact the customer.'
                ) % period_label)

            else:
                line.write({
                    'state': 'failed',
                    'stripe_payment_intent_id': pi_id,
                    'failure_reason': f'Unexpected status: {intent_status}',
                })

        except Exception as e:
            line.write({'state': 'failed', 'failure_reason': str(e)})
            self.message_post(body=_('Payment error for period %s: %s') % (period_label, str(e)))
            raise

    def _create_account_payment(self, period_label, payment_date, amount=None, memo_override=None):
        """Create and post an account.payment record for the collected amount.

        Uses sudo() so the cron (which may run as public user) can write to
        accounting models.  payment_method_line_id is resolved from the
        journal's inbound lines (required in Odoo 18).
        """
        self.ensure_one()
        journal = self.journal_id
        if not journal:
            journal = self.env['account.journal'].sudo().search(
                [('type', 'in', ['bank', 'cash']),
                 ('company_id', '=', self.company_id.id)],
                limit=1,
            )
        if not journal:
            _logger.warning(
                'KGRN Recurring: no bank/cash journal found for contract %s – '
                'payment entry skipped.', self.name
            )
            return False

        # Resolve inbound payment method line (mandatory in Odoo 18)
        inbound_lines = journal.inbound_payment_method_line_ids
        method_line = (
            inbound_lines.filtered(lambda l: l.code == 'manual')[:1]
            or inbound_lines[:1]
        )

        if not method_line:
            _logger.warning(
                'KGRN Recurring: journal %s has no inbound payment method lines configured. '
                'Please enable "Manual" inbound payment method on the journal.',
                journal.name,
            )

        # Use commercial_partner_id so the payment appears as Outstanding Credit
        # on invoices raised against the parent company (Odoo matches partner
        # on receivable lines using commercial_partner_id, not child contacts).
        billing_partner = self.customer_id.commercial_partner_id or self.customer_id
        charge_amount = amount if amount is not None else self.amount
        charge_memo = memo_override or f'KGRN Recurring | {self.name} | {period_label}'

        vals = {
            'partner_id': billing_partner.id,
            'amount': charge_amount,
            'currency_id': self.currency_id.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'journal_id': journal.id,
            'date': payment_date,
            'memo': charge_memo,
            'kgrn_recurring_contract_id': self.id,
        }
        if self.sale_order_id:
            vals['kgrn_sale_order_id'] = self.sale_order_id.id
        if method_line:
            vals['payment_method_line_id'] = method_line.id

        payment = self.env['account.payment'].sudo().create(vals)
        payment.action_post()
        _logger.info(
            'KGRN Recurring: account.payment %s created and posted for contract %s',
            payment.name, self.name,
        )
        return payment

    def action_deduct_advance(self):
        """Charge the advance amount from the customer's card and create an accounting entry."""
        self.ensure_one()
        if self.state != 'running':
            raise UserError(_('Contract must be in Running state to collect the advance.'))
        if not self.stripe_payment_method_id:
            raise UserError(_('No payment card registered on this contract.'))
        if self.advance_amount <= 0:
            raise UserError(_('Advance amount must be greater than zero.'))
        if self.kgrn_advance_paid:
            raise UserError(_('Advance has already been collected for this contract.'))

        today = fields.Date.today()
        period_label = f'Advance – {today.strftime("%d %b %Y")}'

        stripe = self._get_stripe_api()
        amount_cents = int(self.advance_amount * (10 ** self.currency_id.decimal_places))
        description = f'KGRN Advance – {self.name}'
        result = stripe.create_payment_intent(
            amount_cents=amount_cents,
            currency=self.currency_id.name,
            customer_id=self.stripe_customer_id,
            pm_id=self.stripe_payment_method_id,
            description=description,
            contract_ref=self.name,
            period_label=period_label,
        )

        if result.get('error'):
            error_msg = result['error'].get('message', 'Unknown Stripe error')
            raise UserError(_('Stripe error collecting advance: %s') % error_msg)

        intent_status = result.get('status')
        pi_id = result.get('id')

        if intent_status not in ('succeeded', 'processing'):
            raise UserError(_(
                'Stripe payment did not succeed (status: %s). Please try again or contact support.'
            ) % intent_status)

        line = self.env['kgrn.recurring.payment.line'].create({
            'contract_id': self.id,
            'name': f'{self.name} / {period_label}',
            'period_start': today,
            'period_end': today,
            'payment_date': today,
            'amount': self.advance_amount,
            'currency_id': self.currency_id.id,
            'state': 'success',
            'stripe_payment_intent_id': pi_id,
            'processed_by': self.env.user.id,
        })

        account_payment = self._create_account_payment(
            period_label,
            today,
            amount=self.advance_amount,
            memo_override=f'KGRN Advance | {self.name} | {today.strftime("%d %b %Y")}',
        )
        if account_payment:
            line.account_payment_id = account_payment.id

        self.kgrn_advance_paid = True
        self.message_post(
            body=_(
                'Advance of <strong>%s %s</strong> collected on %s (Stripe: %s).'
            ) % (
                self.currency_id.symbol or self.currency_id.name,
                f'{self.advance_amount:,.2f}',
                today.strftime('%d %b %Y'),
                pi_id,
            ),
        )
        self._send_payment_receipt_email(line)
        return {'type': 'ir.actions.act_window_close'}

    # -----------------------------------------------------------------------
    # Notifications
    # -----------------------------------------------------------------------

    def _notify_payment_failure(self, period_label, error_msg):
        """Notify the responsible user AND all Recurring Managers about the failure."""
        self.ensure_one()

        # Collect recipients: responsible user + all manager-group members
        recipients = self.user_id.partner_id
        manager_group = self.env.ref(
            'kgrn_recurring_payment.group_kgrn_recurring_manager',
            raise_if_not_found=False,
        )
        if manager_group:
            recipients |= manager_group.users.mapped('partner_id')
        recipients = recipients.filtered(lambda p: p.email)

        if not recipients:
            _logger.warning('KGRN Recurring: no recipients for failure notification on %s', self.name)
            return

        sym = self.currency_id.symbol or self.currency_id.name
        freq_label = FREQUENCY_LABEL.get(self.frequency, self.frequency)
        sale_ref = f' / {self.sale_order_id.name}' if self.sale_order_id else ''
        email_to = ','.join(recipients.mapped('email'))

        body = f'''<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>Payment Failed</title>
  <!--[if mso]>
  <xml><o:OfficeDocumentSettings><o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>
  <![endif]-->
  <style>
    body, table, td {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table, td {{ mso-table-lspace:0pt; mso-table-rspace:0pt; }}
    body {{ margin:0; padding:0; background-color:#fef2f2; }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#fef2f2;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#fef2f2;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" width="580"><tr><td><![endif]-->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="580" style="max-width:580px;">

        <!-- HEADER -->
        <tr>
          <td bgcolor="#dc2626" style="background-color:#dc2626;padding:24px 36px;border-radius:12px 12px 0 0;mso-border-radius-topright:12px;mso-border-radius-topleft:12px;">
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td>
                  <p style="color:#ffffff;margin:0 0 4px 0;font-size:11px;font-weight:700;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
                    KGRN RECURRING PAYMENTS — INTERNAL ALERT
                  </p>
                  <h1 style="color:#ffffff;margin:0;font-size:20px;font-weight:700;font-family:'Segoe UI',Arial,Helvetica,sans-serif;line-height:1.3;">
                    Payment Failed — Action Required
                  </h1>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- RED ALERT BADGE -->
        <tr>
          <td bgcolor="#fef2f2" style="background-color:#fef2f2;padding:14px 36px;border-left:1px solid #fecaca;border-right:1px solid #fecaca;border-bottom:1px solid #fecaca;">
            <p style="margin:0;font-size:13px;font-weight:700;color:#dc2626;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              &#9888;&#160; A recurring payment could not be processed. Please review and action immediately.
            </p>
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td bgcolor="#ffffff" style="background-color:#ffffff;border-left:1px solid #fecaca;border-right:1px solid #fecaca;padding:28px 36px;">

            <!-- Details table -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;margin:0 0 20px 0;">
              <tr>
                <td width="180" bgcolor="#0d2b45" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:'Segoe UI',Arial,Helvetica,sans-serif;text-transform:uppercase;">
                  Detail
                </td>
                <td bgcolor="#0d2b45" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:'Segoe UI',Arial,Helvetica,sans-serif;text-transform:uppercase;">
                  Value
                </td>
              </tr>
              <tr>
                <td width="180" bgcolor="#f9fafb" style="background-color:#f9fafb;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Contract
                </td>
                <td bgcolor="#f9fafb" style="background-color:#f9fafb;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {self.name}{sale_ref}
                </td>
              </tr>
              <tr>
                <td width="180" bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Customer
                </td>
                <td bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {self.customer_id.name} ({self.customer_email or 'no email'})
                </td>
              </tr>
              <tr>
                <td width="180" bgcolor="#f9fafb" style="background-color:#f9fafb;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Billing Period
                </td>
                <td bgcolor="#f9fafb" style="background-color:#f9fafb;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {period_label}
                </td>
              </tr>
              <tr>
                <td width="180" bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Amount
                </td>
                <td bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;color:#1f2937;font-size:13px;font-weight:700;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {sym}&#160;{self.amount:,.2f} ({freq_label})
                </td>
              </tr>
              <tr>
                <td width="180" bgcolor="#fef2f2" style="background-color:#fef2f2;padding:10px 14px;font-weight:700;color:#dc2626;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #fecaca;border-right:1px solid #fecaca;border-bottom:1px solid #fecaca;">
                  Failure Reason
                </td>
                <td bgcolor="#fef2f2" style="background-color:#fef2f2;padding:10px 14px;color:#dc2626;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #fecaca;border-bottom:1px solid #fecaca;">
                  {error_msg}
                </td>
              </tr>
            </table>

            <p style="font-size:13px;font-weight:700;color:#374151;margin:0 0 8px 0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              Recommended Actions:
            </p>
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 0 0;">
              <tr><td style="padding:4px 0;font-size:13px;color:#374151;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">&#8226;&#160; Open the contract and check the Payment History tab for the Stripe error</td></tr>
              <tr><td style="padding:4px 0;font-size:13px;color:#374151;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">&#8226;&#160; Verify the customer's card has sufficient funds / is not expired</td></tr>
              <tr><td style="padding:4px 0;font-size:13px;color:#374151;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">&#8226;&#160; Use the Manual Deduction button once the card issue is resolved</td></tr>
              <tr><td style="padding:4px 0;font-size:13px;color:#374151;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">&#8226;&#160; Send a new portal link if the customer needs to update their card</td></tr>
            </table>

          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td bgcolor="#f9fafb" align="center" style="background-color:#f9fafb;padding:16px 36px;border:1px solid #fecaca;border-top:none;border-radius:0 0 12px 12px;mso-border-radius-bottomleft:12px;mso-border-radius-bottomright:12px;">
            <p style="font-size:11px;color:#9ca3af;margin:0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              This is an automated internal alert from KGRN Recurring Payments. Do not forward this email.
            </p>
          </td>
        </tr>

      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td>
  </tr>
</table>
</body>
</html>'''

        mail_values = {
            'subject': f'⚠ URGENT: Recurring Payment Failed – {self.name} – {self.customer_id.name}',
            'body_html': body,
            'email_to': email_to,
            'email_from': self.company_id.email or self.env.user.email,
            'res_id': self.id,
            'model': 'kgrn.recurring.contract',
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send(raise_exception=False)

        # Also create an activity on the contract so it shows in the to-do list
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            summary=_('Payment Failed: %s – %s') % (self.name, period_label),
            note=_('Stripe error: %s') % error_msg,
            user_id=self.user_id.id or self.env.uid,
        )

    def _send_payment_receipt_email(self, line):
        """Build and send the payment receipt email directly (no mail.template Jinja2)."""
        self.ensure_one()
        if not self.customer_email:
            return

        sym = self.currency_id.symbol or self.currency_id.name
        contract_name  = self.name
        customer_name  = self.customer_id.name
        period_label   = line.name
        payment_date   = line.payment_date.strftime('%d %b %Y') if line.payment_date else '—'
        amount_str     = f'{line.amount:,.2f}'
        pi_id          = line.stripe_payment_intent_id or ''

        txn_row = ''
        if pi_id:
            txn_row = (
                f'<tr>'
                f'<td width="200" bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;'
                f'font-weight:bold;color:#374151;font-size:13px;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
                f'border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">'
                f'Transaction ID'
                f'</td>'
                f'<td bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;color:#6b7280;'
                f'font-size:11px;font-family:\'Courier New\',Courier,monospace;'
                f'border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">'
                f'{pi_id}'
                f'</td>'
                f'</tr>'
            )

        tax_row = ''
        if self.tax_ids:
            tax_names = ', '.join(self.tax_ids.mapped('name'))
            tax_row = (
                f'<tr>'
                f'<td width="200" bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;'
                f'font-weight:bold;color:#374151;font-size:13px;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
                f'border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">'
                f'Tax Applied'
                f'</td>'
                f'<td bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;color:#6b7280;'
                f'font-size:13px;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
                f'border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">'
                f'{tax_names}'
                f'</td>'
                f'</tr>'
            )

        body = f'''<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>Payment Receipt</title>
  <!--[if mso]>
  <xml>
    <o:OfficeDocumentSettings>
      <o:AllowPNG/>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings>
  </xml>
  <![endif]-->
  <style>
    body, table, td {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table, td {{ mso-table-lspace:0pt; mso-table-rspace:0pt; }}
    body {{ margin:0; padding:0; background-color:#f0f2f5; }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f0f2f5;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f0f2f5;">
  <tr>
    <td align="center" style="padding:24px 12px;">

      <!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" width="600"><tr><td><![endif]-->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;">

        <!-- HEADER -->
        <tr>
          <td bgcolor="#0d2b45" style="background-color:#0d2b45;padding:28px 36px;border-radius:12px 12px 0 0;mso-border-radius-topright:12px;mso-border-radius-topleft:12px;">
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td>
                  <h1 style="color:#ffffff;margin:0 0 4px 0;font-size:20px;font-weight:700;font-family:'Segoe UI',Arial,Helvetica,sans-serif;line-height:1.3;">
                    KGRN Chartered Accountants LLC
                  </h1>
                  <p style="color:#a8c4d8;margin:0;font-size:12px;letter-spacing:1px;text-transform:uppercase;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
                    Payment Receipt
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- GREEN CONFIRMED BADGE -->
        <tr>
          <td bgcolor="#f0fdf4" style="background-color:#f0fdf4;padding:14px 36px;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #dcfce7;">
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td style="font-size:13px;font-weight:700;color:#15803d;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
                  &#10004;&#160; Payment Confirmed – {sym}&#160;{amount_str}
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td bgcolor="#ffffff" style="background-color:#ffffff;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;padding:32px 36px;">

            <p style="margin:0 0 16px 0;font-size:15px;color:#1f2937;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              Dear <strong>{customer_name}</strong>,
            </p>
            <p style="color:#4b5563;line-height:1.65;margin:0 0 24px 0;font-size:14px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              A payment of <strong>{sym}&#160;{amount_str}</strong> has been successfully processed
              for your recurring payment contract. Please find the details below.
            </p>

            <!-- Details table -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;margin:0 0 24px 0;">
              <tr>
                <td width="200" bgcolor="#0d2b45" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:'Segoe UI',Arial,Helvetica,sans-serif;letter-spacing:0.4px;text-transform:uppercase;">
                  Detail
                </td>
                <td bgcolor="#0d2b45" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:'Segoe UI',Arial,Helvetica,sans-serif;letter-spacing:0.4px;text-transform:uppercase;">
                  Value
                </td>
              </tr>
              <tr>
                <td width="200" bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Contract Reference
                </td>
                <td bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {contract_name}
                </td>
              </tr>
              <tr>
                <td width="200" bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Billing Period
                </td>
                <td bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {period_label}
                </td>
              </tr>
              <tr>
                <td width="200" bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Payment Date
                </td>
                <td bgcolor="#f3f4f6" style="background-color:#f3f4f6;padding:10px 14px;color:#1f2937;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {payment_date}
                </td>
              </tr>
              <tr>
                <td width="200" bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;font-weight:700;color:#374151;font-size:13px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  Amount Charged
                </td>
                <td bgcolor="#ffffff" style="background-color:#ffffff;padding:10px 14px;color:#1f2937;font-size:15px;font-weight:700;font-family:'Segoe UI',Arial,Helvetica,sans-serif;border-right:1px solid #e5e7eb;border-bottom:1px solid #e5e7eb;">
                  {sym}&#160;{amount_str}
                </td>
              </tr>
              {txn_row}
              {tax_row}
            </table>

            <p style="font-size:13px;color:#6b7280;margin:0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              If you have any questions regarding this payment, please contact your KGRN account manager.
            </p>

          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td bgcolor="#f9fafb" align="center" style="background-color:#f9fafb;padding:18px 36px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;mso-border-radius-bottomleft:12px;mso-border-radius-bottomright:12px;">
            <p style="font-size:11px;color:#9ca3af;margin:0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
              &#169; KGRN Chartered Accountants LLC. This is an automated receipt. Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
      <!--[if mso]></td></tr></table><![endif]-->

    </td>
  </tr>
</table>
</body>
</html>'''

        mail_values = {
            'subject': f'Payment Receipt \u2013 {contract_name} \u2013 {period_label}',
            'body_html': body,
            'email_to': self.customer_email,
            'email_from': self.company_id.email or self.env.user.email,
            'res_id': self.id,
            'model': 'kgrn.recurring.contract',
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send(raise_exception=False)

    def _notify_card_removal_request(self):
        """Notify the responsible user that the customer has requested card removal."""
        self.ensure_one()
        body = _(
            'Customer <strong>%s</strong> has requested card removal / service cancellation '
            'for contract <strong>%s</strong>.<br/>'
            '<strong>Reason:</strong> %s'
        ) % (self.customer_id.name, self.name, self.card_removal_reason or _('No reason provided'))
        self.message_post(
            body=body,
            partner_ids=[self.user_id.partner_id.id] if self.user_id else [],
            subtype_xmlid='mail.mt_comment',
        )

    # -----------------------------------------------------------------------
    # Payment schedule preview (for portal & form)
    # -----------------------------------------------------------------------

    def get_payment_schedule(self, limit=24):
        """Return a list of upcoming payment dates up to end_date."""
        self.ensure_one()
        if not self.start_date or not self.end_date or not self.frequency:
            return []
        delta = FREQUENCY_DELTA[self.frequency]
        schedule = []
        current = self.next_payment_date or self.start_date
        count = 0
        while current <= self.end_date and count < limit:
            schedule.append(current)
            current = current + delta
            count += 1
        return schedule

    # -----------------------------------------------------------------------
    # Smart button
    # -----------------------------------------------------------------------

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payment History'),
            'res_model': 'kgrn.recurring.payment.line',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }
