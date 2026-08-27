{
    'name': 'Timesheet Extended RK',
    'version': '18.0.1.2',
    'summary': 'Read-only timesheet list, task timers, and the weekly '
               'timesheet compliance report for department heads',
    'category': 'Human Resources',
    'author': 'Rohit',
    'depends': [
        'hr_timesheet',
        'base',
        'account',
        'project',
        'mail',
        # public.holiday and leave.request, used to work out how many days a
        # person was actually expected to work in the week.
        'leave_management_rk',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/timesheet_views.xml',
        'views/project_task_views.xml',
        'views/timesheet_compliance_views.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
