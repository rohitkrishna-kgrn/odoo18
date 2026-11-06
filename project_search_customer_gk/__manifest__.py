{
    'name': 'Project Search Customer',
    'version': '18.0.1.0.5',
    'summary': "Look up a customer from Project, list their Sale Orders and Service Engagements, and open any quotation read-only",
    'description': """
Project > Search Existing Customer.

Copied from crm_search_customer_gk. Differences:

* The menu sits in the Project app, right after Tasks.
* Visible only to users with the "Project Search Customer" checkbox
  (Project Tools section of the user's Access Rights tab).
* Customers and orders are read with sudo, so the user sees every
  quotation regardless of sale record rules or sale access rights.
* Clicking a row opens the sale order form. If the user cannot open it
  (an order of a company not selected in the switcher), a read-only copy
  (header, lines, totals, terms) opens instead.
* The group carries read-only record rules on sale.order and
  sale.order.line, so the opened form shows every order line and its
  values even for a Sales "Own Documents Only" user looking at another
  salesperson's quotation. Editing stays limited to the Sales rights.
* An order opened from the search shows a "Back to Search" button beside
  the breadcrumb. It returns to the page the search was opened from and
  reopens the search with the same customer and results.
""",
    'category': 'Services/Project',
    'author': 'Gokul',
    'depends': ['project', 'sale'],
    'data': [
        'security/project_search_customer_groups.xml',
        'security/ir.model.access.csv',
        'security/project_search_customer_rules.xml',
        'views/project_search_customer_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_search_customer_gk/static/src/js/customer_search_field.js',
            'project_search_customer_gk/static/src/scss/customer_search.scss',
            'project_search_customer_gk/static/src/js/back_to_search.js',
            'project_search_customer_gk/static/src/xml/back_to_search.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
