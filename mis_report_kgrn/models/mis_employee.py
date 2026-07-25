from odoo import models, fields

# Custom hr.employee fields are sensitive (roles, CTC, performance) and must
# never be requested for regular users — otherwise Odoo's employee public-profile
# guard raises "not available for employee public profiles". Restricting the
# fields to HR officers + MIS admins makes Odoo strip them from views/reads for
# everyone else, which resolves that access error.
MIS_EMP_GROUPS = "hr.group_hr_user,mis_report_kgrn.group_mis_admin"


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ── Revenue role (weighted timesheet multiplier) ─────────────────────
    mis_revenue_role_id = fields.Many2one(
        'mis.revenue.role',
        string='Role for MIS',
        ondelete='set null',
        groups=MIS_EMP_GROUPS,
    )

    # ── Performance Management (HR-PMS-001) ──────────────────────────────
    mis_performance_applicable = fields.Boolean(
        string='Under Performance Framework',
        groups=MIS_EMP_GROUPS,
        help="Tick for staff covered by the KGRN Performance Management "
             "Policy (exclude IT, Administration and Internal Accounting).",
    )
    mis_office_location = fields.Selection([
        ('uae',   'UAE'),
        ('india', 'India'),
    ], string='Office Location',
        groups=MIS_EMP_GROUPS,
        help="UAE → 3× monthly / 5× annual CTC. India → 5× monthly / 10× annual CTC.")
    mis_performance_team = fields.Selection([
        ('sales',      'Sales'),
        ('operations', 'Operations (Audit / Tax / Accounting / E-Invoicing)'),
        ('other',      'Other'),
    ], string='Performance Team', groups=MIS_EMP_GROUPS)
    mis_annual_ctc = fields.Monetary(
        string='Annual CTC',
        currency_field='company_currency_id',
        groups=MIS_EMP_GROUPS,
    )
    mis_ramp_start_date = fields.Date(
        string='Ramp-up Start Date',
        groups=MIS_EMP_GROUPS,
        help="Joining date used for the new-joiner ramp-up "
             "(Month 1 = 1×, Month 2 = 2×, Month 3+ = full obligation).",
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
        groups=MIS_EMP_GROUPS,
    )
