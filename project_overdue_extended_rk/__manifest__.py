{
    'name': 'Project Overdue Extended RK',
    'version': '1.0',
    'category': 'Project',
    'summary': 'Track overdue tasks with visual ribbon, list colours, and overdue filters',
    'depends': ['project', 'project_extended_rk', 'my_project_stage_automation'],
    'data': [
        'data/cron_jobs.xml',
        'views/project_task_views.xml',
        'views/project_project_views.xml',
    ],
    'installable': True,
    'application': False,
}
