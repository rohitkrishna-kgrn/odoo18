{
    'name': 'Proposal Workflow Extended RK',
    'version': '18.0.1.12',
    'license': 'LGPL-3',
    'author': 'Rohit',
    'category': 'Sales',
    'summary': 'Product scope/methodology, quotation proposal builder and KGRN proposal PDF',
    'description': """
Proposal workflow
=================
* Scope of work, methodology and deliverables maintained on the product, plus an
  eInvoicing reporting flag.
* A Proposal tab on the quotation that collects the scope and methodology of every
  service on the order, together with the overall terms & conditions — all editable
  per proposal.
* Download Proposal on quotations, producing the KGRN eInvoicing Services Proposal PDF.
* Download SE once the linked pipeline record reaches Service Engagement.
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
        'report/report_paperformat.xml',
        'report/report_proposal.xml',
        'report/report_proposal_templates.xml',
        'report/report_se_templates.xml',
        'views/product_template_views.xml',
        'views/crm_lead_views.xml',
        'views/sale_order_views.xml',
        'views/einvoicing_dashboard_views.xml',
        'views/salesperson_performance_views.xml',
        'views/salesperson_performance_wizard_views.xml',
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
