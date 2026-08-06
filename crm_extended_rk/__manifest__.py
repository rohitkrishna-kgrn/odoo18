{
    'name': 'CRM Extended RK',
    'version': '1.1',
    'depends': [
        'account',
        'sale',              # For sale.order and sale.order.line
        'sale_crm',          # Bridge: crm.lead <-> sale.order (order_ids, quotation button)
        'sale_order_approval',  # approval_state + approve/confirm/cancel flow
        'crm',               # Your base CRM module
        'mail',              # Chatter logging + outbound discovery email
        'product',           # For product.product model
        'project',           # For project.project model
        'base',              # Always safe to include base
    ],
    'author': 'Rohit',
    'category': 'Sales',
    'summary': 'Extends Sale Order with CRM-related fields and a client discovery form',
    'data': [
        'security/ir.model.access.csv',
        'data/crm_stage_data.xml',
        'data/crm_tag_data.xml',
        'views/sale_order_views.xml',
        'views/crm_lead_discovery_form_views.xml',
        'views/crm_lead_views.xml',
        'views/crm_lead_source_wizard_views.xml',
        'views/crm_lead_reason_wizard_views.xml',
        'reports/discovery_report.xml',
        'templates/discovery_form.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'crm_extended_rk/static/src/css/crm_lead_form.css',
            'crm_extended_rk/static/src/js/crm_lead_statusbar.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
