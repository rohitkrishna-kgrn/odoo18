{
    'name': 'HR Document Management',
    'version': '18.0.1.34.0',
    'category': 'Human Resources',
    'summary': 'Secure per-employee document repository with role-based access, '
               'confidential categories, audit trail and personal details form',
    'author': 'KGRN Audit',
    'website': 'https://www.kgrnaudit.com',
    'depends': ['hr', 'mail'],
    'data': [
        'security/hr_dms_security.xml',
        'security/ir.model.access.csv',
        'security/hr_dms_rules.xml',
        'data/hr_dms_data.xml',
        'data/hr_dms_mail_templates.xml',
        'wizards/reject_wizard_views.xml',
        'views/hr_dms_category_views.xml',
        'views/hr_dms_document_views.xml',
        'views/hr_dms_personal_details_views.xml',
        'views/hr_dms_audit_log_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_dms_export_views.xml',
        'views/hr_dms_dashboard_views.xml',
        'views/hr_dms_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_dms/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
