from odoo import fields, models


class PaymentProvider(models.Model):
    """Extend payment.provider to ensure Stripe credential fields exist.

    If the payment_stripe module is already installed these fields are already
    present and Odoo's ORM will safely merge the declarations.
    If payment_stripe is NOT installed we add the fields so our module can
    still read / write Stripe credentials through the payment provider record.
    """

    _inherit = 'payment.provider'

    stripe_publishable_key = fields.Char(
        string='Stripe Publishable Key',
        help='Your Stripe publishable key (starts with pk_live_ or pk_test_).',
    )
    stripe_secret_key = fields.Char(
        string='Stripe Secret Key',
        help='Your Stripe secret key (starts with sk_live_ or sk_test_). Keep this confidential.',
        groups='base.group_system',
    )
    stripe_webhook_secret = fields.Char(
        string='Stripe Webhook Secret',
        help='Webhook signing secret from your Stripe dashboard (starts with whsec_).',
        groups='base.group_system',
    )
