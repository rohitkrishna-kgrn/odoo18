{
    'name': 'CRM Extended RK',
    'version': '1.0',
    'depends': [
        'account',
        'sale',      # For sale.order and sale.order.line
        'crm',       # Your base CRM module
        'product',   # For product.product model
        'project',   # For project.project model
        'base',      # Always safe to include base
    ],
    'author': 'Rohit',
    'category': 'Sales',
    'summary': 'Extends Sale Order with CRM-related fields',
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}
