from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KgrnStripeConfig(models.TransientModel):
    """KGRN Stripe Configuration wizard.

    Provides a single place to switch the Stripe provider between Test /
    Live / Disabled modes and to manage publishable/secret/webhook keys,
    without navigating into the raw payment.provider form.
    """

    _name = 'kgrn.stripe.config'
    _description = 'KGRN Stripe Configuration'

    # ── Provider selection ────────────────────────────────────────────────

    stripe_provider_id = fields.Many2one(
        'payment.provider',
        string='Stripe Provider',
        domain=[('code', '=', 'stripe')],
        required=True,
    )

    # ── Mode ─────────────────────────────────────────────────────────────

    stripe_mode = fields.Selection(
        selection=[
            ('test', 'Test Mode  (use Stripe test keys & test cards)'),
            ('enabled', 'Live Mode  (real charges – use live keys)'),
            ('disabled', 'Disabled'),
        ],
        string='Stripe Mode',
        required=True,
        default='test',
    )

    # ── Test credentials ─────────────────────────────────────────────────

    stripe_test_publishable_key = fields.Char(
        string='Test Publishable Key',
        help='Starts with  pk_test_',
    )
    stripe_test_secret_key = fields.Char(
        string='Test Secret Key',
        help='Starts with  sk_test_',
    )

    # ── Live credentials ─────────────────────────────────────────────────

    stripe_live_publishable_key = fields.Char(
        string='Live Publishable Key',
        help='Starts with  pk_live_',
    )
    stripe_live_secret_key = fields.Char(
        string='Live Secret Key',
        help='Starts with  sk_live_',
    )

    # ── Shared ───────────────────────────────────────────────────────────

    stripe_webhook_secret = fields.Char(
        string='Webhook Signing Secret',
        help='Starts with  whsec_  — register the endpoint in your Stripe Dashboard.',
    )

    # ── Active keys (read-only display) ──────────────────────────────────

    active_publishable_key = fields.Char(
        string='Active Publishable Key',
        compute='_compute_active_keys',
    )
    active_secret_key = fields.Char(
        string='Active Secret Key',
        compute='_compute_active_keys',
    )

    @api.depends('stripe_mode', 'stripe_test_publishable_key',
                 'stripe_live_publishable_key', 'stripe_test_secret_key',
                 'stripe_live_secret_key')
    def _compute_active_keys(self):
        for rec in self:
            if rec.stripe_mode == 'test':
                rec.active_publishable_key = rec.stripe_test_publishable_key or ''
                rec.active_secret_key = rec.stripe_test_secret_key or ''
            elif rec.stripe_mode == 'enabled':
                rec.active_publishable_key = rec.stripe_live_publishable_key or ''
                rec.active_secret_key = rec.stripe_live_secret_key or ''
            else:
                rec.active_publishable_key = ''
                rec.active_secret_key = ''

    # ── Default: load from existing provider ─────────────────────────────

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        provider = self.env['payment.provider'].search(
            [('code', '=', 'stripe')], limit=1
        )
        if not provider:
            return res

        pub_key  = getattr(provider, 'stripe_publishable_key', '') or ''
        sec_key  = getattr(provider, 'stripe_secret_key', '') or ''
        wh_secret = getattr(provider, 'stripe_webhook_secret', '') or ''
        mode = provider.state  # 'test' | 'enabled' | 'disabled'

        res.update({
            'stripe_provider_id': provider.id,
            'stripe_mode': mode,
            'stripe_webhook_secret': wh_secret,
        })

        # Distribute current keys into the correct bucket
        if pub_key.startswith('pk_test'):
            res['stripe_test_publishable_key'] = pub_key
        elif pub_key.startswith('pk_live'):
            res['stripe_live_publishable_key'] = pub_key

        if sec_key.startswith('sk_test'):
            res['stripe_test_secret_key'] = sec_key
        elif sec_key.startswith('sk_live'):
            res['stripe_live_secret_key'] = sec_key

        return res

    # ── Save ─────────────────────────────────────────────────────────────

    def action_save(self):
        self.ensure_one()
        provider = self.stripe_provider_id
        if not provider:
            raise UserError(_('Please select a Stripe provider.'))

        mode = self.stripe_mode

        # Choose which key pair to activate based on mode
        if mode == 'test':
            pub_key = self.stripe_test_publishable_key or ''
            sec_key = self.stripe_test_secret_key or ''
            if pub_key and not pub_key.startswith('pk_test'):
                raise UserError(_('Test Publishable Key must start with  pk_test_'))
            if sec_key and not sec_key.startswith('sk_test'):
                raise UserError(_('Test Secret Key must start with  sk_test_'))
        elif mode == 'enabled':
            pub_key = self.stripe_live_publishable_key or ''
            sec_key = self.stripe_live_secret_key or ''
            if pub_key and not pub_key.startswith('pk_live'):
                raise UserError(_('Live Publishable Key must start with  pk_live_'))
            if sec_key and not sec_key.startswith('sk_live'):
                raise UserError(_('Live Secret Key must start with  sk_live_'))
        else:
            pub_key = ''
            sec_key = ''

        write_vals = {'state': mode}
        if hasattr(provider, 'stripe_publishable_key'):
            write_vals['stripe_publishable_key'] = pub_key
        if hasattr(provider, 'stripe_secret_key'):
            write_vals['stripe_secret_key'] = sec_key
        if hasattr(provider, 'stripe_webhook_secret'):
            write_vals['stripe_webhook_secret'] = self.stripe_webhook_secret or ''

        provider.sudo().write(write_vals)

        mode_label = dict(self._fields['stripe_mode'].selection)[mode].split('(')[0].strip()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Stripe Configuration Saved'),
                'message': _(
                    'Stripe provider "%s" is now set to  %s.'
                ) % (provider.name, mode_label),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_open_stripe_dashboard(self):
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://dashboard.stripe.com',
            'target': 'new',
        }
