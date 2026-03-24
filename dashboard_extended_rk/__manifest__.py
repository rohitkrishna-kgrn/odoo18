{
    'name': 'Dashboard Extended RK',
    'version': '1.0',
    'summary': 'Custom dashboard config for sales',
    'author': 'Rohit',
    'depends': ['sale_management'],
    'data': [
        'security/ir.model.access.csv',
        'views/dashboard_config_views.xml',
    ],
    'installable': True,
    'application': False,
}
