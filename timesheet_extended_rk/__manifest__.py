{
    'name': 'Timesheet Extended RK',
    'version': '1.0',
    'summary': 'Make Timesheet list view read-only',
    'category': 'Human Resources',
    'author': 'Rohit',
    'depends': ['hr_timesheet','base','account','project'],
    'data': [
        'security/ir.model.access.csv',
        'views/timesheet_views.xml',
        'views/project_task_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
