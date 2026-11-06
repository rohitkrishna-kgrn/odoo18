{
    'name': 'CRM Mail Leads RK',
    'version': '18.0.1.14',
    'author': 'Rohit',
    'category': 'Sales/CRM',
    'summary': 'Pull mail from dedicated Gmail inboxes into CRM Mail Leads '
               'and hand them to a salesperson as pipeline records',
    'description': """
CRM Mail Leads
==============

Adds a CRM-owned incoming mail configuration that is completely separate from
Odoo's standard *Settings > Technical > Incoming Mail Servers* (fetchmail):

* **CRM > Configuration > Incoming Mail Servers (CRM)** - one record per Gmail
  inbox, each carrying the CRM tag that identifies where the mail came from
  (``DM`` / ``Einvoicing``).
* A dedicated cron runs **every 2 minutes** and pulls every mail that has
  arrived since the previous run - **read or unread**. It tracks an IMAP UID
  watermark rather than the unread flag, so a mail somebody opened on their
  phone before the cron got to it still arrives. Nothing else in the mailbox
  is touched.
* **CRM > Mail Leads** lists every pulled mail with its source tag. Each row has
  an **Assign To** button that asks for a salesperson and then creates the
  matching CRM pipeline record. A **Fetch Mails** button in the list header
  pulls in every older mail that is not yet a Mail Lead - read or unread, any
  age - from the Inbox, **most recent first**; it keeps importing
  automatically in the background (a few hundred messages per cron beat) and
  the total keeps climbing on its own, press after press, until the whole
  mailbox is caught up. Once history is in, the button is simply an
  **immediate** version of the 2-minute pass: press it and anything that has
  just landed is in the list at once, instead of waiting for the next beat.
* **Keywords per mailbox.** Each CRM mailbox has a *Keywords* list (started
  from its Mail Lead Tag, e.g. "e-invoice, e-invoicing" for Einvoicing).
  Every mail is still imported, but only mail whose subject or message
  contains one of the words is shown in Mail Leads and sends the admin alert;
  the rest stays hidden (no filter needed) until the *Not Matched* filter is
  picked. Matching ignores
  case, matches the start of a word, and accepts the parts of a keyword
  joined, spaced or hyphenated ("e-invoice" = "einvoice" = "e invoice").
  Empty Keywords = every mail counts as relevant.
* Access is one dropdown on the user form, *CRM Mail Leads*:

  - **User** - sees CRM > Mail Leads and assigns mail to salespeople.
  - **Administrator** - everything a User can do, plus mailbox
    configuration (CRM > Configuration > Incoming Mail Servers (CRM)),
    create/delete Mail Leads (including assigned ones), **and an e-mail
    alert for every new Mail Lead** whose tag the admin picked under
    *Mail Lead Alert Tags* (user form > Access Rights, or My Preferences).
    Only mail received in the last 3 days is announced, so the Fetch Mails
    backlog walk never sends a flood of alerts. The wording is the e-mail
    template *CRM Mail Leads: New Mail Lead alert*. Alerts go out only as
    outgoing e-mails (Settings > Technical > Email > Emails) and stay listed
    there after sending.
* **Internal staff are never shown as the lead.** When a colleague forwards a
  client enquiry into one of the inboxes, the ``From`` header names the
  colleague, not the client. Mail from an internal address is therefore read
  further: the forwarded header block, then the forwarding headers, then the
  body, until the original **external** sender is found - and that is what
  **From** and **Contact Name** show. The colleague is kept on a separate
  *Forwarded By* field for the audit trail. **Every mail is still imported** -
  when no external client can be found the record arrives complete, with only
  From / Contact Name left empty. The internal domains are configurable in
  *Settings > Technical > System Parameters*
  (``crm_mail_lead_rk.internal_domains``, default ``kgrnaudit.com``).
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
        'data/ir_config_parameter_data.xml',
        'data/mail_template_data.xml',
        'views/crm_mail_server_views.xml',
        'views/crm_mail_lead_views.xml',
        'wizard/crm_mail_lead_assign_wizard_views.xml',
        'views/crm_mail_lead_menus.xml',
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
