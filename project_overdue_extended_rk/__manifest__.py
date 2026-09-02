{
    'name': 'Project Overdue Extended RK',
    'version': '18.0.1.2.0',
    'category': 'Project',
    'summary': 'Track overdue tasks with visual ribbon, list colours, overdue filters and a delay-reason wizard',
    # my_project_stage_automation was declared here but nothing in this module
    # references it: every view inherits a core project.* view, and the only
    # state_additional values used ('completed', 'cancelled') come from
    # project_extended_rk. Carrying it would have pulled in firm-wide
    # auto-cancel automation and a post-install hook as a side effect of
    # installing the delay log.
    'depends': ['project', 'project_extended_rk'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron_jobs.xml',
        'wizards/delay_log_wizard_views.xml',
        'views/project_task_views.xml',
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_overdue_extended_rk/static/src/js/delay_log_form_controller.js',
        ],
    },
    'installable': True,
    'application': False,
}
