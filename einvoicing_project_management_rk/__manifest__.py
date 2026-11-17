# -*- coding: utf-8 -*-
{
    "name": "E-Invoicing Project Management",
    "summary": "Phase 1 e-invoicing project tracker per TRN, and the SEs still waiting to be listed",
    "description": """
E-Invoicing Project Management
==============================

* **Phase 1 Projects** - one row per Emaratax legal name / TRN: Peppol ID, the
  Service Engagement (SE) it belongs to, Gap Assessment, UAT Onboarding,
  Emaratax Onboarding, LIVE Middleware and remarks. Every change is tracked in
  the chatter.
* **Unidentified** - the same columns for projects whose SE is not known
  yet; **Add** moves a row into Phase 1 Projects (pre-filled form, the row is
  archived once the Phase 1 row is saved).
* **Invoice quota** - UAT and LIVE sections on the form: AR / AP / overall
  used, limit, remaining and overage from the KGRN platform, looked up by
  Peppol ID (NA without one). Endpoints under Configuration.
* **Sale order** - an E-Invoicing button beside AML opens a dashboard for that
  SE: entities, listed, pending, onboarding, quotas and every TRN.
* **Pending** - approved eInvoicing SEs whose Entities tab lists more entities
  than there are Phase 1 Project rows for that SE, with the shortfall.
* **Dashboard** - an OWL dashboard over both: KPI tiles, onboarding progress,
  Gap Assessment and Emaratax splits, renewals by month, pending SEs, upcoming
  renewals and a per-salesperson view. Every figure opens its rows.
* Subscription Start Date and Renewal Date per row, filled from the SE's order
  lines (earliest Engagement Start; day after the latest Engagement End).
""",
    "author": "KGRN Chartered Accountants",
    "website": "https://kgrnaudit.com",
    "category": "Services/Project",
    "version": "18.0.1.3.1",
    "license": "LGPL-3",
    # crm_extended_rk: sale.order.einvoicing_service and the Entities tab
    # (sale.order.entity). sale_order_approval: sale.order.approval_state.
    "depends": ["web", "mail", "sale_management", "crm_extended_rk", "sale_order_approval",
                "aml_automation_extended_rk"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/quota_config_data.xml",
        "data/ir_cron.xml",
        "views/quota_templates.xml",
        "views/quota_config_views.xml",
        "views/phase1_project_views.xml",
        "views/unidentified_views.xml",
        "views/phase1_pending_views.xml",
        "views/sale_order_views.xml",
        "wizard/so_dashboard_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "einvoicing_project_management_rk/static/src/dashboard/dashboard.scss",
            "einvoicing_project_management_rk/static/src/dashboard/dashboard.js",
            "einvoicing_project_management_rk/static/src/dashboard/dashboard.xml",
            "einvoicing_project_management_rk/static/src/quota/quota.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
