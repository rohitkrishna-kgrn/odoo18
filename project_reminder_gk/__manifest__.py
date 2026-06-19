{
    'name': 'Project Reminder GK',
    'version': '18.0.1.0.0',
    'summary': 'Periodic reminder management for projects — yearly, half-yearly, quarterly and monthly',
    'category': 'Project',
    'author': 'KGRN',
    'depends': [
        'project',
        'sale',
        'mail',
        'project_extended_rk',
        'crm_extended_rk',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_templates.xml',
        'data/cron_jobs.xml',
        'views/project_reminder_schedule_views.xml',
        'views/project_reminder_wizard_views.xml',
        'views/project_project_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_reminder_gk/static/src/js/period_date_field.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
