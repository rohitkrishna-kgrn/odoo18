{
    'name': 'Task Transfer RK',
    'version': '1.0',
    'depends': ['project', 'project_extended_rk', 'mail'],
    'author': 'KGRN',
    'category': 'Project',
    'summary': 'Transfer tasks between team members with full tracking and notifications',
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/res_users_view.xml',
        'data/ir_sequence.xml',
        'views/task_transfer_wizard_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
