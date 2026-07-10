from odoo import models, fields


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # ── Revenue role (weighted timesheet multiplier) ─────────────────────
    mis_revenue_role_id = fields.Many2one(
        'mis.revenue.role',
        string='Role for MIS',
        ondelete='set null',
    )

    # ── Performance Management (HR-PMS-001) ──────────────────────────────
    mis_performance_applicable = fields.Boolean(
        string='Under Performance Framework',
        help="Tick for staff covered by the KGRN Performance Management "
             "Policy (exclude IT, Administration and Internal Accounting).",
    )
    mis_office_location = fields.Selection([
        ('uae',   'UAE'),
        ('india', 'India'),
    ], string='Office Location',
        help="UAE → 3× monthly / 5× annual CTC. India → 5× monthly / 10× annual CTC.")
    mis_performance_team = fields.Selection([
        ('sales',      'Sales'),
        ('operations', 'Operations (Audit / Tax / Accounting / E-Invoicing)'),
        ('other',      'Other'),
    ], string='Performance Team')
    mis_annual_ctc = fields.Monetary(
        string='Annual CTC',
        currency_field='company_currency_id',
    )
    mis_ramp_start_date = fields.Date(
        string='Ramp-up Start Date',
        help="Joining date used for the new-joiner ramp-up "
             "(Month 1 = 1×, Month 2 = 2×, Month 3+ = full obligation).",
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
