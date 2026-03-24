{
    'name': 'Planning RK',
    'version': '1.0',
    'summary': 'Task planning with stages and Kanban',
    'author': 'Rohit',
    'category': 'Project',
    'depends': ['project','mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/planning_stage_data.xml',
        'views/planning_views.xml',
        'views/task_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
