{
    'name': 'Invoice Template RK',
    'version': '1.0',
    'summary': 'Custom invoice template (Template RK) and auto send',
    'description': 'Provides custom invoice layout and auto attaches it when sending mail.',
    'author': 'Rohit',
    'license': 'AGPL-3',
    'depends': ['account', 'mail'],
    'data': [
        'data/report_action.xml',
        'views/report_invoice_template.xml',
        'views/res_company_views.xml'
    ],
    'installable': True,
    'application': False,
}
