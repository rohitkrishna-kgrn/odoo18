{
    'name': 'MIS Dashboard RK',
    'version': '1.0',
    'summary': 'Project-wise MIS Dashboard',
    'description': 'Custom MIS Dashboard showing tasks grouped by project (Done stage)',
    'category': 'Project',
    'author': 'RK',
    'depends': [
        'base',
        'project',
        'sale',
        'account',
        'hr'
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'views/mis_dashboard_views.xml',
        'views/mis_dashboard_invoice.xml',
        # 'views/mis_dashboard_se_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
