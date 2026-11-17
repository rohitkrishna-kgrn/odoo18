{
    'name': 'Quotation AML-First Approval',
    'version': '18.0.1.4.0',
    'category': 'Sales',
    'summary': 'Quotation approval first, then the AML/KYC step',
    'description': """
Quotation approval first, then AML/KYC:

* Submit for Approval sends the Quotation Approver a branded To-Do + email
  (with an Open button), from the company email. The AML team is not told yet.
* While the quotation is To Approve, the Quotation Approver sees "Approve".
* Once Approved, the AML Managers get an email, and "Send AML Form" /
  "AML Bypass" appear (AML team or Quotation Approver).
* AML/KYC Completed is ticked automatically when the AML request is Approved,
  Bypassed or Cancelled by the AML team (not by cancelling the quotation).
* An Approved quotation can be confirmed (and its project created) without
  AML/KYC being Completed.
    """,
    'author': 'KGRN',
    'depends': [
        'sale_order_approval',
        'aml_automation_extended_rk',
    ],
    'data': [
        'views/sale_order_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
