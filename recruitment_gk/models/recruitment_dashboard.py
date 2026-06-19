from odoo import models, fields, api, _


class RecruitmentDashboard(models.Model):
    _name = 'recruitment.dashboard'
    _description = 'Recruitment Dashboard'
    _order = 'id'

    name = fields.Char(default='Recruitment Dashboard', readonly=True)

    # ── Recruitment Request stats ──────────────────────────────────────────
    total_open_requests = fields.Integer(
        compute='_compute_request_stats', string='Open Requests',
    )
    total_pending_requests = fields.Integer(
        compute='_compute_request_stats', string='Pending Requests',
    )
    total_closed_requests = fields.Integer(
        compute='_compute_request_stats', string='Closed Requests',
    )

    # ── Candidate stats ────────────────────────────────────────────────────
    total_candidates = fields.Integer(
        compute='_compute_candidate_stats', string='Total Candidates',
    )
    candidates_under_review = fields.Integer(
        compute='_compute_candidate_stats', string='Under Review',
    )
    candidates_in_interview = fields.Integer(
        compute='_compute_candidate_stats', string='In Interview',
    )
    selected_candidates = fields.Integer(
        compute='_compute_candidate_stats', string='Selected Candidates',
    )
    rejected_candidates = fields.Integer(
        compute='_compute_candidate_stats', string='Rejected Candidates',
    )

    # ── IT Onboarding stats ────────────────────────────────────────────────
    it_onboarding_pending = fields.Integer(
        compute='_compute_it_stats', string='IT Onboarding Pending',
    )
    it_onboarding_completed = fields.Integer(
        compute='_compute_it_stats', string='IT Onboarding Completed',
    )

    @api.depends()
    def _compute_request_stats(self):
        Request = self.env['recruitment.request']
        for rec in self:
            rec.total_open_requests = Request.search_count([
                ('state', 'in', ('submitted', 'hr_review', 'in_progress', 'interview')),
            ])
            rec.total_pending_requests = Request.search_count([
                ('state', 'in', ('draft', 'submitted', 'hr_review')),
            ])
            rec.total_closed_requests = Request.search_count([
                ('state', '=', 'closed'),
            ])

    @api.depends()
    def _compute_candidate_stats(self):
        Candidate = self.env['recruitment.candidate']
        for rec in self:
            rec.total_candidates = Candidate.search_count([])
            rec.candidates_under_review = Candidate.search_count([
                ('state', 'in', ('manager_review', 'hm_approved')),
            ])
            rec.candidates_in_interview = Candidate.search_count([
                ('state', '=', 'interview'),
            ])
            rec.selected_candidates = Candidate.search_count([
                ('state', '=', 'selected'),
            ])
            rec.rejected_candidates = Candidate.search_count([
                ('state', '=', 'rejected'),
            ])

    @api.depends()
    def _compute_it_stats(self):
        IT = self.env['recruitment.it.onboarding']
        for rec in self:
            rec.it_onboarding_pending = IT.search_count([
                ('state', 'in', ('pending', 'in_progress')),
            ])
            rec.it_onboarding_completed = IT.search_count([
                ('state', '=', 'completed'),
            ])

    @api.model
    def action_open_dashboard(self):
        """Return the singleton dashboard record, creating it if needed."""
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.sudo().create({'name': 'Recruitment Dashboard'})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recruitment Dashboard'),
            'res_model': 'recruitment.dashboard',
            'res_id': dashboard.id,
            'view_mode': 'form',
            'target': 'current',
            'flags': {'mode': 'readonly'},
        }
