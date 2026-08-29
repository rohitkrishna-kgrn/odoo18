{
    'name': 'Debit Note Ledger',
    'version': '18.0.1.3.0',
    'category': 'Accounting/Accounting',
    'summary': 'Dedicated ledger menus for Customer and Vendor Debit Notes',
    'description': """
Adds "Debit Notes" ledger menus under Accounting > Customers and
Accounting > Vendors, listing invoices/bills created via the
Add Debit Note wizard, mirroring the existing Credit Notes / Refunds menus.
""",
    'depends': ['account', 'account_debit_note', 'account_extended_rk'],
    'data': [
        'views/debit_note_menus.xml',
        'views/account_move_views.xml',
        'views/account_journal_dashboard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
