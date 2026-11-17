{
    'name': 'Quotation AML-First Approval',
    'version': '18.0.1.3.0',
    'category': 'Sales',
    'summary': 'AML/KYC runs alongside quotation approval',
    'description': """
Moves the AML/KYC step in front of quotation approval:

* Submit for Approval sends the Quotation Approver the usual To-Do + email
  and also emails the AML Manager group so the AML/KYC step can start.
* While the quotation is To Approve, the Quotation Approver sees "Approve"
  straight away, plus "AML Bypass" until AML/KYC is Completed.
* AML/KYC Completed is ticked automatically when the AML request is Approved,
  Bypassed or Cancelled by the AML team (not by cancelling the quotation).
  No extra email goes to the Quotation Approver at that point.
* Once the quotation is Approved it can be confirmed (and its project
  created) without AML/KYC being Completed.
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
