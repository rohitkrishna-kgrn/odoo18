{
    'name': 'Weekly Overdue Invoice Report GK',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': "Monday-morning report of invoices >30 days overdue, with a mandatory "
               "'Why Not Collected' reason from the PM, sent only to selected users",
    'author': 'KGRN',
    'depends': [
        'account',
        'mail',
        'account_extended_rk',
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/account_move_views.xml',
        'views/weekly_overdue_invoice_report_log_views.xml',
        'report/weekly_overdue_invoice_report_templates.xml',
        'data/ir_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'weekly_overdue_invoice_report_gk/static/src/js/why_not_collected_dialog.js',
            'weekly_overdue_invoice_report_gk/static/src/js/why_not_collected_dialog.xml',
            'weekly_overdue_invoice_report_gk/static/src/js/account_move_form_controller.js',
            'weekly_overdue_invoice_report_gk/static/src/js/ar_aging_list_controller.js',
        ],
    },
    'installable': True,
    'application': False,
}
