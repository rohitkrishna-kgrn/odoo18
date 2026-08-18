{
    'name': 'Account Extended RK',
    'version': '1.4',
    'category': 'Accounting',
    'summary': 'Mandatory AR Responsible and Service Engagement on invoices, locked late-payment penalty footer',
    'depends': [
        'account',
        'sale',
        'sale_project',
        'project_extended_rk',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/ar_aging_dashboard_views.xml',
        'data/ar_aging_cron.xml',
    ],
    'installable': True,
    'application': False,
}
