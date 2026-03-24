{
    'name': 'Project Task Templates',
    'version': '1.0',
    'depends': ['project', 'sale', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_task_views.xml',
    ],
    'installable': True,
    'application': False,
}
