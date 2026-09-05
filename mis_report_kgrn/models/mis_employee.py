from odoo import models, fields, api

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
        ('audit',      'Audit'),
        ('tax',        'Tax'),
        ('accounting', 'Accounting'),
        ('einvoicing', 'E-Invoicing'),
        ('other',      'Other'),
    ], string='Performance Team', groups=MIS_EMP_GROUPS,
        help="Employees previously tagged 'Operations' need to be re-tagged "
             "into one of Audit / Tax / Accounting / E-Invoicing for the "
             "Performance Management Report's Team Totals to include them.")
    mis_annual_ctc = fields.Monetary(
        string='Annual CTC',
        currency_field='company_currency_id',
        groups=MIS_EMP_GROUPS,
    )
    mis_ramp_start_date = fields.Date(
        string='Ramp-up Start Date',
        groups=MIS_EMP_GROUPS,
        help="Joining date used for the new-joiner ramp-up "
             "(Month 1 = 1×, Month 2 = 2×, Month 3+ = full obligation). "
             "Leave blank to use the employee's first contract start date, "
             "which is what the scorecard falls back to; set it only to "
             "override that — e.g. for a re-hire or a mid-contract transfer.",
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
        groups=MIS_EMP_GROUPS,
    )

    # ── Warning Notice counter (HR-PMS-001 §Escalation) ──────────────────
    # Surfaced on the employee so HR can see an active escalation without
    # opening the MIS menus. Kept under the same restricted groups as the
    # rest of the block, otherwise Odoo's employee public-profile guard
    # raises "not available for employee public profiles" for normal users.
    mis_warning_notice_ids = fields.One2many(
        'mis.warning.notice', 'employee_id',
        string='Performance Escalations',
        groups=MIS_EMP_GROUPS,
    )
    mis_warning_notice_count = fields.Integer(
        string='Escalations',
        compute='_compute_mis_warning_notice',
        groups=MIS_EMP_GROUPS,
    )
    mis_hr_flagged = fields.Boolean(
        string='Flagged for HR',
        compute='_compute_mis_warning_notice',
        search='_search_mis_hr_flagged',
        groups=MIS_EMP_GROUPS,
        help="An escalation case is currently open: the employee has missed the "
             "minimum monthly obligation for 2 or more consecutive months.",
    )
    mis_consecutive_below_target = fields.Integer(
        string='Consecutive Months Below Minimum',
        compute='_compute_mis_warning_notice',
        groups=MIS_EMP_GROUPS,
    )

    def _compute_mis_warning_notice(self):
        Notice = self.env['mis.warning.notice'].sudo()
        counts = dict(Notice._read_group(
            [('employee_id', 'in', self.ids)], ['employee_id'], ['__count'],
        ))
        open_cases = Notice.search([
            ('employee_id', 'in', self.ids),
            ('state', 'in', ['flagged', 'draft', 'issued']),
        ])
        by_employee = {c.employee_id.id: c for c in open_cases}
        for emp in self:
            case = by_employee.get(emp.id)
            emp.mis_warning_notice_count = counts.get(emp, 0)
            emp.mis_hr_flagged = bool(case)
            emp.mis_consecutive_below_target = case.consecutive_months if case else 0

    def _search_mis_hr_flagged(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError(
                "mis_hr_flagged only supports searching = / != True or False")
        flagged = self.env['mis.warning.notice'].sudo().search([
            ('state', 'in', ['flagged', 'draft', 'issued']),
        ]).employee_id.ids
        positive = (operator == '=') == bool(value)
        return [('id', 'in' if positive else 'not in', flagged)]

    def action_run_mis_warning_notice_check(self):
        """Re-run the Warning Notice counter for this employee alone — lets HR
        refresh or test one person without touching everybody else's cases."""
        return self.env['mis.warning.notice'].sudo().action_run_escalation_now(
            employee_ids=self.ids)

    def action_open_mis_warning_notices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Performance Escalations',
            'res_model': 'mis.warning.notice',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    # ── MIS Coach group auto-sync ────────────────────────────────────────
    # "Coach" is never assigned by hand: whoever currently appears as
    # someone's coach_id belongs to group_mis_coach (which gates the Coach
    # View menu/report), and nobody else does. Recomputed from scratch on
    # every relevant change so an employee dropped as the last coachee of a
    # coach correctly drops that coach out of the group too.
    @api.model
    def _sync_mis_coach_group(self):
        group = self.env.ref('mis_report_kgrn.group_mis_coach', raise_if_not_found=False)
        if not group:
            return
        coach_user_ids = self.env['hr.employee'].sudo().search(
            [('coach_id', '!=', False)]
        ).mapped('coach_id.user_id').ids
        group.sudo().write({'users': [(6, 0, coach_user_ids)]})

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if any('coach_id' in vals for vals in vals_list):
            employees._sync_mis_coach_group()
        return employees

    def write(self, vals):
        result = super().write(vals)
        if 'coach_id' in vals or 'active' in vals:
            self._sync_mis_coach_group()
        return result

    def unlink(self):
        result = super().unlink()
        self._sync_mis_coach_group()
        return result
