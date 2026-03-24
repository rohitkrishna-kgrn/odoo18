{
    'name': 'Project Extended RK',
    'version': '1.0',
    'depends': ['project', 'sale', 'sale_timesheet', 'account', 'hr_timesheet', 'dms'],
    'author': 'Rohit',
    'category': 'Project',
    'data': [
        'views/project_groups.xml',
        'views/project_project_views.xml',
        'views/project_team_views.xml',
        'views/project_task_views.xml',
        'security/res_users_view.xml',
        'security/ir.model.access.csv',
        'data/email_template.xml'

    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
