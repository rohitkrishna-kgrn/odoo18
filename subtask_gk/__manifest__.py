{
    'name': 'Sub-Task GK',
    'version': '18.0.1.0.0',
    'summary': 'Sub-task system with hour control and timesheet integration',
    'category': 'Project',
    'author': 'GK',
    'depends': [
        'project',
        'hr_timesheet',
        'project_extended_rk',
        'timesheet_extended_rk',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/subtask_wizard_views.xml',
        'views/project_task_views.xml',
        'views/timesheet_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'subtask_gk/static/src/subtask_kanban_default.js',
            'subtask_gk/static/src/subtask_remaining_field.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
