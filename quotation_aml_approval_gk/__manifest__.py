{
    'name': 'Quotation AML-First Approval',
    'version': '18.0.1.1.0',
    'category': 'Sales',
    'summary': 'AML/KYC must be completed before a quotation can be approved',
    'description': """
Moves the AML/KYC step in front of quotation approval:

* Submit for Approval emails the AML Manager group (not the Quotation Approver).
* While the quotation is To Approve, the Quotation Approver sees only
  "AML Bypass"; "Approve" appears once AML/KYC Completed is ticked.
* AML/KYC Completed is ticked automatically when the AML request is Approved,
  Bypassed or Cancelled by the AML team (not by cancelling the quotation).
  At that moment the Quotation Approver gets a To-Do
  and an email, and "AML Bypass" disappears.
* Orders that were already approved before this module keep the old
  post-approval Send AML Form / AML Bypass buttons, so they can still finish.
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
