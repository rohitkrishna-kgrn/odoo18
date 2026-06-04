{
    'name': 'MIS Dashboard',
    'version': '18.0.3.0.0',
    'summary': 'Project-wise MIS Dashboard & Outstanding Report',
    'category': 'Project',
    'author': 'KGRN',
    'depends': [
        'base',
        'project',
        'sale',
        'sale_project',
        'account',
        'hr',
    ],
    'data': [
        'security/groups.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'views/mis_res_users_view.xml',
        'views/mis_project_wise_views.xml',
        'views/mis_outstanding_views.xml',
        'views/mis_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mis_report_kgrn/static/src/scss/mis_dashboard.scss',
            'mis_report_kgrn/static/src/xml/mis_dashboard.xml',
            'mis_report_kgrn/static/src/js/mis_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
