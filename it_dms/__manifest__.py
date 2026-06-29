{
    'name': 'IT Document Management System',
    'version': '18.0.1.0.5',
    'category': 'Technical',
    'summary': 'Centralized IT Documentation Repository for IT Departments',
    'description': """
IT Document Management System (IT-DMS)
========================================
A comprehensive document management system built for IT departments.

Key Features:
- Centralized document repository with file attachments
- Hierarchical folder management (unlimited depth)
- Category and tag-based document organization
- Document version history tracking
- Advanced search and filtering
- Role-based access control (Admin / Engineer / Viewer)
- Dashboard with live statistics
- Full chatter & activity tracking (mail.thread)
- Supports: SOPs, Server Docs, Network Diagrams, Licenses, Manuals, and more
    """,
    'author': 'KGRN Audit',
    'website': 'https://www.kgrnaudit.com',
    'depends': ['base', 'mail'],
    'data': [
        'security/it_dms_security.xml',
        'security/ir.model.access.csv',
        'security/it_dms_record_rules.xml',
        'data/it_dms_sequence.xml',
        'data/it_dms_data.xml',
        'views/it_category_views.xml',
        'views/it_tag_views.xml',
        'views/it_folder_views.xml',
        'views/it_document_version_views.xml',
        'views/it_document_views.xml',
        'views/it_dashboard_views.xml',
        'report/it_document_report_views.xml',
        'views/it_menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': [],
}
