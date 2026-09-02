{
    'name': 'Account Extended RK',
    'version': '2.13',
    'category': 'Accounting',
    'summary': 'Mandatory AR Responsible and Sale Order Line on invoices (the service engagement is derived from that line), locked late-payment penalty footer, a settle/close lock on invoices over 180 days outstanding, a collection follow-up log fed from the invoice chatter (each Log note and each completed activity is recorded with its date, method and the client response, and feeds the AR reports), an auto-flag for invoices over 30 days overdue with no follow-up logged, and retainership contracts that raise draft invoices on a recurring schedule for finance to review and post, auto-archiving of customer invoices left unapproved in draft for 7 days (creator warned 2 days before), and an automated customer Credit Hold at 180 days overdue that blocks new projects and proposals until the arrears clear, with a single-use Managing Partner override, and an engagement billing plan (advance / progress / completion milestones) that every Completion invoice is checked against before it can be posted',
    'depends': [
        'account',
        'sale',
        'sale_project',
        'product',
        'mail',
        'project_extended_rk',
        # sale.order.advance_amount -- the figure the billing plan is derived
        # from when no milestones have been entered by hand.
        'crm_extended_rk',
        # sale.order.action_submit_for_approval, gated for customers on hold
        'sale_order_approval',
        # account.move.project_manager_ids, the Project Manager field the
        # hold notification is addressed to
        'account_move_project_team_rk',
        # om_account_followup.menu_finance_followup -- the Follow-Ups menu the
        # No Follow-Up Logged and Invoice Follow-up Log entries hang off.
        'om_account_followup',
    ],
    'data': [
        'security/retainership_groups.xml',
        'security/ir.model.access.csv',
        'data/retainership_sequence.xml',
        'views/account_move_views.xml',
        'views/account_followup_log_views.xml',
        'views/mail_activity_type_views.xml',
        'data/followup_activity_type.xml',
        'views/billing_milestone_views.xml',
        'views/account_move_completion_views.xml',
        'views/ar_aging_dashboard_views.xml',
        'views/product_template_views.xml',
        'views/retainership_contract_views.xml',
        'views/retainership_invoice_views.xml',
        'data/ar_aging_cron.xml',
        'data/retainership_cron.xml',
        'views/credit_hold_views.xml',
        'views/credit_hold_gate_views.xml',
        'data/stale_draft_cron.xml',
        'data/credit_hold_cron.xml',
    ],
    'installable': True,
    'application': False,
}
