{
    'name': 'AML Automation Extended',
    'version': '18.0.1.0.0',
    'category': 'Accounting/AML',
    'summary': 'AML KYC workflow with portal web form, user pipeline and manager approval.',
    'description': """
        AML Automation Extended module for UAE AML/CFT compliance.
        - Sends KYC web form to client on sale order approval
        - Multi-page portal form (Entity / Individual / UBO / Directors / Shareholders / Documents)
        - AML Manager review: Accept, Bypass, Cancel
        - AML User pipeline: In Progress, HIT detection, Additional info flow
        - Automated email notifications and scheduled reports
    """,
    'author': 'KGRN',
    'depends': [
        'sale_management',
        'mail',
        'portal',
        'website',
        'sale_order_approval',
    ],
    'data': [
        'security/aml_groups.xml',
        'security/ir.model.access.csv',
        'data/aml_sequences.xml',
        'data/aml_mail_templates.xml',
        'data/aml_cron.xml',
        'views/aml_request_views.xml',
        'views/wizard_views.xml',
        'views/sale_order_views.xml',
        'views/aml_menus.xml',
        'templates/portal_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'aml_automation_extended_rk/static/src/css/aml_portal.css',
            'aml_automation_extended_rk/static/src/js/aml_portal.js',
        ],
        'web.assets_backend': [
            'aml_automation_extended_rk/static/src/css/aml_backend.css',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
