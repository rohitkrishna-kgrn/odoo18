{
    'name': 'eInvoicing Extended RK',
    'version': '1.0.1',
    'category': 'Accounting',
    'summary': 'KGRN eInvoicing (UAE FTA Phase 2 / PINT-AE) — AR outbound push and AP inbound webhook',
    'description': """
KGRN eInvoicing Platform integration
===================================

**AR — outbound** (Odoo -> KGRN -> Peppol / FTA)

* Customer invoice   -> ``380`` Standard Tax Invoice  (or ``389`` Self-Billed Invoice)
* Customer credit note -> ``381`` Credit Note         (or ``261`` Self-Billed Credit Note)
* Full PINT-AE field map on the invoice, the invoice line, the partner, the
  product, the unit of measure and the tax.
* ``POST {base}/external/outbound/invoice`` — single or batch (<= 200),
  idempotent on ``UniqueInvoiceNumber``, ``PushState`` draft or submit.
* ``GET {base}/external/outbound/whoami`` — token smoke test.
* ``POST {base}/access-token/generate`` — issue the ``kgrn_out_`` token from
  the portal credentials, without the portal UI.

**AP — inbound** (KGRN -> Odoo)

* Token-authenticated webhook at ``/einvoicing/ap/webhook``.
* ``ap.invoice.received``     (``380`` / ``389``) -> Vendor Bill
* ``ap.credit_note.received`` (``381`` / ``261``) -> Vendor Credit Note
* ``erp.webhook.test`` connectivity probe answered with ``200``.
* Idempotent on ``document.instanceId`` (upsert, never a duplicate).

Configured per company in **Settings -> Accounting -> KGRN eInvoicing**.
    """,
    'author': 'KGRN Chartered Accountants',
    'website': 'https://kgrnaudit.com',
    'depends': [
        'account',
        'account_edi_ubl_cii',
        'product',
        'uom',
    ],
    'data': [
        'security/einvoicing_security.xml',
        'security/ir.model.access.csv',
        'data/einvoicing_data.xml',
        'data/ir_cron.xml',
        'views/einvoice_log_views.xml',
        'views/einvoice_allowance_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/uom_views.xml',
        'views/account_tax_views.xml',
        'views/res_country_state_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/einvoice_token_wizard_views.xml',
        'views/einvoicing_menus.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
