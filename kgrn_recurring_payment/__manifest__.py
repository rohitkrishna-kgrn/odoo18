{
    'name': 'KGRN Recurring Payment',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Finance',
    'summary': 'Professional recurring payment management with Stripe integration for KGRN',
    'description': """
KGRN Recurring Payment Management
===================================
A professional recurring payment module for managing subscription-based billing
with Stripe integration. Features include:

- Recurring contract management (weekly / monthly / quarterly / half-yearly / yearly)
- Stripe card collection via a secure, branded customer portal
- Automated payment processing via scheduled cron jobs
- Full accounting integration (creates account.payment records)
- Customer card management with controlled removal workflow
- Complete audit trail with payment history
- Internal user manual and guided workflow
    """,
    'author': 'KGRN',
    'depends': [
        'account',
        'mail',
        'portal',
        'payment',
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence.xml',
        'data/email_templates.xml',
        'data/cron_jobs.xml',
        # Wizard views
        'wizard/views/kgrn_user_manual_wizard_views.xml',
        'wizard/views/kgrn_send_portal_link_wizard_views.xml',
        'wizard/views/kgrn_card_removal_action_views.xml',
        'wizard/views/kgrn_manual_deduction_wizard_views.xml',
        # Portal
        'views/portal_templates.xml',
        # Backend views
        'views/kgrn_stripe_config_views.xml',
        'views/kgrn_recurring_contract_views.xml',
        'views/kgrn_recurring_payment_line_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_frontend': [],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
