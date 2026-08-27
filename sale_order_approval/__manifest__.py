{
    "name": "Sale Order Approval",
    "version": "1.1",
    "summary": "Submit quotation for approval and confirm with custom sequence",
    "author" : "Rohit Krishna",
    "depends": ["sale", "product"],
    "data": [
        "views/sale_order_views.xml",
        "views/res_company_views.xml",
        "views/res_users_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
