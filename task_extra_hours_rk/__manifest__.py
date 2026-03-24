{
    'name': 'Task Extra Hours Request',
    'version': '1.0',
    'depends': ['project'],
    'category': 'Project',
    'summary': 'Request and approve extra hours on project tasks',
    'data': [
        'security/ir.model.access.csv',
        'views/wizard_views.xml',
        'views/project_task_views.xml',
        'views/task_extra_hours_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
}
