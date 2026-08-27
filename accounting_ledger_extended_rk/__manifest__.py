# -*- coding: utf-8 -*-
{
    'name': 'Accounting Ledger Extended (RK)',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Tally-like General Partner Ledger and Outstanding Partner '
               'Ledger with PDF/Excel export and Friday outstanding emails.',
    'description': """
Tally style Partner Ledgers
===========================
* General Partner Ledger (debit/credit/running balance, narration)
* Outstanding Partner Ledger (only open invoices)
* Excel (xlsx) and PDF export with a clean Tally-like UI
* Per customer outstanding email notification (default OFF, disabled until
  verified by an accountant)
* Weekly (every Friday) automated outstanding email with all open invoices
  attached as PDF, branded with the company logo.
""",
    'author': 'KGRN',
    'company': 'KGRN',
    'website': 'https://www.kgrnaudit.com',
    'depends': ['account', 'mail', 'account_extended_rk'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template.xml',
        'data/ir_cron.xml',
        'report/ledger_report.xml',
        'report/ledger_report_templates.xml',
        'views/res_partner_views.xml',
        'views/ledger_menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'accounting_ledger_extended_rk/static/src/css/ledger.css',
            'accounting_ledger_extended_rk/static/src/xml/general_ledger.xml',
            'accounting_ledger_extended_rk/static/src/xml/outstanding_ledger.xml',
            'accounting_ledger_extended_rk/static/src/js/general_ledger.js',
            'accounting_ledger_extended_rk/static/src/js/outstanding_ledger.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
