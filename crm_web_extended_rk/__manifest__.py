{
    'name': 'CRM Web Extended RK',
    'version': '18.0.1.0.0',
    'category': 'CRM',
    'summary': 'Web lead intake via webhook with allocation workflow and field mapping',
    'depends': ['crm', 'mail'],
    'data': [
        'security/crm_web_extended_groups.xml',
        'security/ir.model.access.csv',
        'views/field_map_views.xml',
        'views/web_lead_views.xml',
        'views/web_lead_menus.xml',
        'data/field_map_defaults.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
