{
    "name": "Project Transfer RK",
    "version": "18.0.1.0.0",
    "summary": "Transfer projects from one user to another",
    "author": "Rohit",
    "depends": ["project", "project_extended_rk"],
    "data": [
        'security/project_transfer_groups.xml',
        "security/ir.model.access.csv",
        "views/project_transfer_wizard_view.xml",
        "views/project_list_transfer_wizard_views.xml",
        "views/project_project_mark_done.xml"
    ],
    "installable": True,
    "application": False,
}
