{
    'name': 'CRM Manager Access',
    'version': '18.0.1.2.1',
    'summary': "Managers also see the CRM and Services records of everyone below them "
               "in the Employee > Manager hierarchy (read and edit)",
    # Plain text on purpose: without it Odoo renders README.md as
    # reStructuredText and prints docutils errors on every install/upgrade.
    'description': """
CRM Manager Access
==================

Adds a Manager level to the Sales access dropdown (between User: Own Documents Only
and User: All Documents). Managers can view and edit the CRM leads,
quotations, service engagements and order lines of everyone below them in the
Employee > Manager hierarchy, at every level. Create and delete rights are unchanged.

Technical documentation: README.md in the module folder.
""",
    'category': 'Sales/CRM',
    'author': 'Gokul',
    # project_assigned_gk owns res.users.gk_manager_chain_ids (the stored
    # Employee > Manager chain the rules match on); crm_extended_rk owns the
    # Services own-orders filter that sale_order.py widens.
    'depends': ['crm', 'sale', 'hr', 'project_assigned_gk', 'crm_extended_rk'],
    'data': [
        'security/crm_manager_security.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
