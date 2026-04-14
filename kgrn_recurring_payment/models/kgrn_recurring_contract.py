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
    'weekly': relativedelta(weeks=1),
    'monthly': relativedelta(months=1),
    'quarterly': relativedelta(months=3),
    'half_yearly': relativedelta(months=6),
    'yearly': relativedelta(years=1),
}

FREQUENCY_LABEL = {
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
    # Accounting
    # -----------------------------------------------------------------------

    journal_id = fields.Many2one(
        'account.journal',
        string='Payment Journal',
        domain=[('type', 'in', ['bank', 'cash'])],
        help='Journal used to post recurring payment entries.',
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

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Recurring Amount must be greater than zero.'))

    # -----------------------------------------------------------------------
    # CRUD
    # -----------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('kgrn.recurring.contract') or 'New'
            if not vals.get('access_token'):
                vals['access_token'] = uuid.uuid4().hex
        return super().create(vals_list)

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

    def _create_account_payment(self, period_label, payment_date):
        """Create and post an account.payment record for the collected amount."""
        self.ensure_one()
        journal = self.journal_id
        if not journal:
            journal = self.env['account.journal'].search(
                [('type', 'in', ['bank', 'cash']), ('company_id', '=', self.company_id.id)],
                limit=1,
            )
        if not journal:
            _logger.warning('No payment journal found for contract %s', self.name)
            return False

        try:
            payment = self.env['account.payment'].create({
                'partner_id': self.customer_id.id,
                'amount': self.amount,
                'currency_id': self.currency_id.id,
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'journal_id': journal.id,
                'date': payment_date,
                'ref': f'{self.name} / {period_label}',
                'memo': (
                    f'KGRN Recurring Payment – {self.name} – '
                    f'{FREQUENCY_LABEL[self.frequency]} – {period_label}'
                ),
            })
            payment.action_post()
            return payment
        except Exception as e:
            _logger.error('Failed to create account payment for %s: %s', self.name, e)
            return False

    # -----------------------------------------------------------------------
    # Notifications
    # -----------------------------------------------------------------------

    def _notify_payment_failure(self, period_label, error_msg):
        template = self.env.ref(
            'kgrn_recurring_payment.email_template_payment_failed', raise_if_not_found=False
        )
        if template:
            template.with_context(
                period_label=period_label,
                error_msg=error_msg,
            ).send_mail(self.id, force_send=True, raise_exception=False)

    def _send_payment_receipt_email(self, line):
        template = self.env.ref(
            'kgrn_recurring_payment.email_template_payment_receipt', raise_if_not_found=False
        )
        if template:
            template.send_mail(line.id, force_send=True, raise_exception=False)

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
