{
    'name': 'CRM Mail Leads RK',
    'version': '18.0.1.2',
    'author': 'Rohit',
    'category': 'Sales/CRM',
    'summary': 'Pull unread mail from dedicated Gmail inboxes into CRM Mail Leads '
               'and hand them to a salesperson as pipeline records',
    'description': """
CRM Mail Leads
==============

Adds a CRM-owned incoming mail configuration that is completely separate from
Odoo's standard *Settings > Technical > Incoming Mail Servers* (fetchmail):

* **CRM > Configuration > Incoming Mail Servers (CRM)** - one record per Gmail
  inbox, each carrying the CRM tag that identifies where the mail came from
  (``DM`` / ``Einvoicing``).
* A dedicated cron runs **every 2 minutes** and pulls only the mails that are
  still **unread** and that arrived **since the previous run**. Nothing else in
  the mailbox is touched.
* **CRM > Mail Leads** lists every pulled mail with its source tag. Each row has
  an **Assign To** button that asks for a salesperson and then creates the
  matching CRM pipeline record. A **Fetch Now** button in the list header pulls
  every still-unread mail that has not been imported yet, on demand.
* A dedicated access group, *CRM / Mail Leads*, gates that menu.
""",
    'depends': [
        'base',
        'mail',        # message_parse() + EmailMessage handling
        'sales_team',  # salesperson groups the new group implies
        'crm',         # crm.lead / crm.tag / CRM menus
    ],
    'data': [
        'security/crm_mail_lead_security.xml',
        'security/ir.model.access.csv',
        'data/crm_tag_data.xml',
        'data/ir_cron_data.xml',
        'views/crm_mail_server_views.xml',
        'views/crm_mail_lead_views.xml',
        'wizard/crm_mail_lead_assign_wizard_views.xml',
        'views/crm_mail_lead_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
