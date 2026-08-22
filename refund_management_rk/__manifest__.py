{
    'name': 'Refund Management RK',
    'version': '18.0.1.2.0',
    'category': 'Accounting',
    'summary': 'Reimbursement and Upselling',
    'description': """Manage Reimbursement Requests with Excel Upload and Review.""",
    'depends': ['base', 'mail', 'sale', 'account'],
    'data': [
        'security/refund_security.xml',
        'security/ir.model.access.csv',
        'data/reimbursement_sequence.xml',
        'data/upselling_config_data.xml',
        'wizards/upload_excel_wizard_view.xml',
        'wizards/attach_bills_wizard_view.xml',
        'wizards/upselling_reset_wizard_view.xml',
        'wizards/upselling_reject_wizard_view.xml',
        'views/reimbursement_views.xml',
        'views/menus.xml',
        'views/upselling_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'refund_management_rk/static/src/js/upselling_chatter.js',
        ],
    },
    'installable': True,
    'application': True,
}
