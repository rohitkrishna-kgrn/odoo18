# my_project_stage_automation/__manifest__.py
{
    'name': 'Project Stage Automation',
    'version': '1.0',
    'category': 'Project',
    'summary': 'Automatically manage project and task stages based on task completion and approval',
    'depends': ['project', 'sale'],
    'data': [
        'views/project_task_views.xml',
    ],
    'installable': True,
    'application': False,
}
