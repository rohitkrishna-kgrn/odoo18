{
    'name': 'Project Assigned GK',
    'version': '18.0.1.5.0',
    'summary': 'Project Users only see projects and tasks they manage, are assigned to, or are a team member of; Project Managers also see their direct reports\' work',
    'category': 'Project',
    'author': 'KGRN',
    # project_extended_rk defines task.team_member_ids used by the rules
    'depends': ['project', 'hr', 'project_extended_rk', 'sale_timesheet'],
    'data': [
        'security/ir.model.access.csv',
        'security/project_visibility_rules.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
