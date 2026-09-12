{
    'name': 'Invoice Template RK',
    'version': '18.0.1.3',
    'summary': 'KGRN UAE FTA tax-invoice PDF layout for customer invoices',
    'description': """
Replaces the standard customer-invoice PDF with the KGRN UAE tax-invoice
format (FTA / Federal Decree-Law No. 8 of 2017): supplier block with TRN,
invoice details with date of supply, customer block with TRN, a per-line
VAT-rate / VAT-amount / total-incl-VAT table, subtotal / VAT / total-payable
summary, amount in words, bank details, terms &amp; conditions and a signature
block. Every value is derived from the invoice at render time.

The same layout is used by "Send &amp; Print" and by the Print menu, and both
report actions are kept flagged as invoice reports so Odoo lets the invoice
be e-mailed.
""",
    'author': 'Rohit',
    'license': 'AGPL-3',
    'depends': ['account', 'mail'],
    'data': [
        'data/report_action.xml',
        'views/report_invoice_template.xml',
        'views/res_company_views.xml'
    ],
    'installable': True,
    'application': False,
}
