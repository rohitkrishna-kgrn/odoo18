{
    'name': 'CRM Search Customer',
    'version': '18.0.1.0.0',
    'summary': "Look up a customer from CRM and list their Sale Orders and Service Engagements (read-only)",
    'category': 'Sales/CRM',
    'author': 'Gokul',
    'depends': ['crm', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_search_custom_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'crm_search_customer_gk/static/src/js/customer_search_field.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
