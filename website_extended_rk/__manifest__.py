{
    'name': 'Website Extended RK - Custom Login',
    'version': '18.0.1.0.0',
    'category': 'Website',
    'summary': 'Custom company login page replacing Odoo default website login.',
    'author': 'KGRN',
    'depends': [
        'website',
        'web',
        'portal',
        'auth_signup',
    ],
    'data': [
        'templates/login.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
