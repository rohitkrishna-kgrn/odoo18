{
    'name': 'Contact Extended RK',
    'version': '1.0',
    'summary': 'Extend Contacts with Emirates ID, Passport, and Company License',
    'description': 'This module adds Emirates ID, Passport Number, and Company License Number to contacts and makes all contact fields mandatory.',
    'category': 'Contacts',
    'author': 'RK',
    'depends': ['contacts', 'mail', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template.xml',
        'report/contact_form_report.xml',
        'views/res_partner_views.xml',
        'views/customer_form_templates.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
