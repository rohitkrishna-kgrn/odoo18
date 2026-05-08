{
    'name': 'Project Stage Automation',
    'version': '1.4',
    'category': 'Project',
    'summary': 'Automatically cancel projects and tasks when a linked sale order is cancelled',
    'depends': ['project', 'sale', 'project_extended_rk', 'base_automation'],
    'data': [
        'data/project_stages.xml',
        'data/automation.xml',
        'views/project_task_views.xml',
        'views/sale_order_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
