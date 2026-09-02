{
    "name": "Sale Renewal RK",
    "version": "18.0.1.2",
    "category": "Sales/Project",
    "summary": "Renew sale order from completed project",
    "depends": ["sale", "sales_team", "project", "crm_extended_rk"],
    "data": [
        "security/sale_order_security.xml",
        "views/project_view.xml",
    ],
    "installable": True,
    "application": False,
}
