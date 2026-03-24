# -*- coding: utf-8 -*-
{
    'name': 'Import Statement RK',
    'version': '18.0.1.0.0',
    'summary': 'Import Bank Statement from XLSX file',
    'author': 'RK',
    'category': 'Accounting',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/import_statement_views.xml',
    ],
    'installable': True,
    'application': False,
}
