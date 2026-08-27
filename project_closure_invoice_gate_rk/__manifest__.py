{
    "name": "Project Closure Invoice Gate",
    "version": "18.0.1.0.0",
    "category": "Project",
    "summary": "Block Project (and its Tasks) closure until the Project Manager confirms invoicing",
    "description": """
Locks the 'Done' transition on project.project (and, by extension,
project.task) until the Project Manager confirms one of:
  a) an invoice raised in Odoo (selected from existing account.move records,
     must be posted and linked to this project as its Service Engagement), or
  b) an invoice raised in a group company (PM attaches a document and enters
     the invoice number, date and value manually).

A task can only reach 'Done' once its own project has confirmed invoicing.
The block applies regardless of entry point (workflow buttons, bulk close
actions, kanban drag, or direct field edits).
""",
    "author": "Rohit",
    "depends": ["project", "project_extended_rk", "account_extended_rk"],
    "data": [
        "views/project_project_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
}
