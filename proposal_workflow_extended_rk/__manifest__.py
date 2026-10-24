{
    'name': 'Proposal Workflow Extended RK',
    'version': '18.0.1.33',
    'license': 'LGPL-3',
    'author': 'Rohit',
    'category': 'Sales',
    'summary': 'eInvoicing services, CRM pipeline link and Proposal / SE PDFs from the KGRN PDF API',
    'description': """
Proposal workflow
=================
* eInvoicing reporting flag on the product, and the four eInvoicing services
  (Readiness, Onboarding & ASP Linking, ERP Integration, Annual Subscription &
  Support) that replace the archived S1-S8 catalogue.
* Download Proposal on quotations and Download SE once approved, both rendered by
  the KGRN eInvoicing PDF API (URL and key in Settings → CRM → Proposal PDF API).
* A CRM Pipeline link required while a new quotation is being created (with a
  logged override); already-saved quotations stay editable without it, and a
  CRM reference (CRM0000001) on every pipeline record.
""",
    'depends': [
        'sale',
        'sale_crm',
        'crm',
        'mail',
        'product',
        'crm_extended_rk',
        'sale_order_approval',
        'sale_renewal_rk',
    ],
    'data': [
        'security/einvoicing_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/product_data.xml',
        'views/product_template_views.xml',
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
        'views/einvoicing_dashboard_views.xml',
        'views/salesperson_performance_views.xml',
        'views/salesperson_performance_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'proposal_workflow_extended_rk/static/src/scss/einvoicing_dashboard.scss',
            'proposal_workflow_extended_rk/static/src/js/einvoicing_dashboard.js',
            'proposal_workflow_extended_rk/static/src/js/einvoicing_analytics.js',
            'proposal_workflow_extended_rk/static/src/xml/einvoicing_dashboard.xml',
            'proposal_workflow_extended_rk/static/src/xml/einvoicing_analytics.xml',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
