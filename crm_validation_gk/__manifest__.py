{
    'name': 'CRM Validation',
    'version': '18.0.1.5.0',
    'summary': "Block duplicate proposals and customers with a similar name",
    'category': 'Sales/CRM',
    'author': 'Gokul',
    'description': """
CRM Validation
==============
A quotation cannot be created (or duplicated) when a quotation or sales order
created before it, and not cancelled, is for the same customer, has a line for
the same service (product), and that line's engagement period overlaps this
one's - or, whatever the dates, the earlier one is still an open quotation whose
engagement has not ended yet. The same check refuses adding such a line or switching to such a
customer on a saved quotation, and runs again on Submit for Approval and
Download Proposal. A warning lists the existing proposal(s); the later copy
stays blocked until the first one is cancelled. Renewals (Renew on a project)
are exempt, since they copy the previous order's dates by design.

A new customer cannot be created when an active customer with a similar name
already exists - case, spacing, punctuation and a trailing legal form (LLC,
L L C, FZCO, FZE, FZ-LLC, Ltd, DMCC, ...) are ignored, so "SILVER PALM" and
"Silver Palm" clash. Checked when a person saves a contact, quick-creates one from
a field, renames one, or converts a lead with "Create a new customer". Contact
persons under a company, and server flows (website leads, referrals, imports),
are not checked.

Otherwise everything works exactly as before.
""",
    'depends': ['proposal_workflow_extended_rk'],
    'data': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
