{
    'name': 'Invoice Project Manager & Team Member RK',
    'version': '18.0.1.0',
    'license': 'LGPL-3',
    'author': 'Rohit',
    'category': 'Accounting',
    'summary': 'Project Manager and Team Member columns on the customer invoice list',
    'description': """
Invoice delivery people
=======================
Adds two read-only columns to the customer invoice list:

* **Project Manager** — the managers set on the sale order lines the invoice bills.
* **Team Member** — the team members on the still-open tasks of the projects
  behind those sale orders.

Both render as badges (many2many tags).
""",
    'depends': [
        'account',
        'sale',
        'sale_project',
        'crm_extended_rk',        # sale.order.line.manager_id
        'project_extended_rk',    # project.task.team_member_ids, project.sale_order_id
    ],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
}
