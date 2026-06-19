import re
import pytz
from datetime import datetime
from markupsafe import Markup, escape
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class RecruitmentCandidate(models.Model):
    _name = 'recruitment.candidate'
    _description = 'Recruitment Candidate'
    _inherit = ['recruitment.gk.base', 'mail.thread', 'mail.activity.mixin']
    _order = 'sort_priority asc, id desc'

    name = fields.Char('Candidate Name', required=True, tracking=True)
    request_id = fields.Many2one(
        'recruitment.request', 'Recruitment Request',
        ondelete='set null', tracking=True,
    )
    stage_id = fields.Many2one(
        'recruitment.stage', 'Stage',
        tracking=True, copy=False,
        default=lambda self: self._default_stage(),
        group_expand='_read_group_stage_ids',
    )
    # ── personal info ──────────────────────────────────────────────────────
    phone_country_code = fields.Selection([
        ('+971', '+971 (UAE)'),
        ('+91',  '+91  (India)'),
        ('+966', '+966 (Saudi Arabia)'),
        ('+974', '+974 (Qatar)'),
        ('+965', '+965 (Kuwait)'),
        ('+973', '+973 (Bahrain)'),
        ('+968', '+968 (Oman)'),
        ('+1',   '+1   (USA / Canada)'),
        ('+44',  '+44  (UK)'),
        ('+61',  '+61  (Australia)'),
        ('+60',  '+60  (Malaysia)'),
        ('+65',  '+65  (Singapore)'),
        ('+92',  '+92  (Pakistan)'),
        ('+94',  '+94  (Sri Lanka)'),
        ('+880', '+880 (Bangladesh)'),
        ('+63',  '+63  (Philippines)'),
        ('+62',  '+62  (Indonesia)'),
        ('+49',  '+49  (Germany)'),
        ('+33',  '+33  (France)'),
        ('+86',  '+86  (China)'),
        ('+81',  '+81  (Japan)'),
    ], string='Country Code', default='+971')
    phone = fields.Char('Contact Number', required=True)
    email = fields.Char('Email Address', required=True)
    current_company = fields.Char('Current Company')
    current_designation = fields.Char('Current Designation')
    total_experience = fields.Selection(
        [(str(i), '%d Year%s' % (i, 's' if i != 1 else '')) for i in range(0, 51)],
        'Total Experience (Years)',
    )
    total_experience_months = fields.Selection(
        [(str(i), '%d Month%s' % (i, 's' if i != 1 else '')) for i in range(1, 12)],
        'Total Experience (Months)',
    )
    relevant_experience = fields.Selection(
        [(str(i), '%d Year%s' % (i, 's' if i != 1 else '')) for i in range(0, 51)],
        'Relevant Experience (Years)',
    )
    relevant_experience_months = fields.Selection(
        [(str(i), '%d Month%s' % (i, 's' if i != 1 else '')) for i in range(1, 12)],
        'Relevant Experience (Months)',
    )
    salary_currency = fields.Selection([
        ('aed', 'AED – UAE Dirham'),
        ('inr', 'INR – Indian Rupees'),
    ], string='Salary Currency', default='aed')
    current_salary = fields.Float('Current Salary')
    expected_salary = fields.Float('Expected Salary')
    notice_period = fields.Char('Notice Period')
    skills = fields.Text('Skills')
    key_skills = fields.Text('Key Skills')
    technologies = fields.Text('Technologies')
    certifications = fields.Text('Certifications')
    cv_attachment_ids = fields.Many2many(
        'ir.attachment',
        'recruitment_candidate_cv_rel',
        'candidate_id', 'attachment_id',
        string='CV / Resume',
    )
    hr_remarks = fields.Text('HR Remarks')
    rejection_remark = fields.Text('Rejection Remarks')
    sent_manager_id = fields.Many2one('res.users', 'Sent to Manager', tracking=True)
    # ── state & kanban ─────────────────────────────────────────────────────
    state = fields.Selection([
        ('new', 'New'),
        ('draft', 'Draft'),
        ('manager_review', 'Manager Review'),
        ('hm_approved', 'Approved by HM'),
        ('interview', 'In Interview'),
        ('interview_completed', 'Interview Completed'),
        ('selected', 'Selected'),
        ('rejected', 'Rejected'),
    ], 'Status', default='new', tracking=True, copy=False)
    priority = fields.Selection([
        ('0', 'Normal'), ('1', 'Good'),
        ('2', 'Very Good'), ('3', 'Excellent'),
    ], default='0')
    color = fields.Integer('Color Index')
    # Selected candidates float to the top of list views (0 = top, 1 = below)
    sort_priority = fields.Integer(
        compute='_compute_sort_priority',
        store=True,
        string='Sort Priority',
    )
    # ── interviews ─────────────────────────────────────────────────────────
    interview_ids = fields.One2many(
        'recruitment.interview.round', 'candidate_id', 'Interview Rounds',
        order='round_order asc',
    )
    interview_count = fields.Integer(
        compute='_compute_interview_count',
        store=True,
        aggregator='sum',
    )
    # ── all-rounds-selected flag (stored so it can be used in domains) ────
    all_rounds_selected = fields.Boolean(
        compute='_compute_all_rounds_selected',
        store=True,
        string='All Rounds Selected',
    )
    # ── all rounds passed flag — True only after every round is in 'passed' state ──
    all_rounds_passed = fields.Boolean(
        compute='_compute_all_rounds_passed',
        store=True,
        string='All Rounds Passed',
    )
    # ── True when every non-cancelled round has reached 'completed' or beyond ──
    all_rounds_completed = fields.Boolean(
        compute='_compute_all_rounds_completed',
        store=True,
        string='All Rounds Completed',
    )
    # ── related (stored for search/group_by) ──────────────────────────────
    job_title = fields.Char(related='request_id.job_title', store=True)
    department_id = fields.Many2one(related='request_id.department_id', store=True)
    hiring_manager_id = fields.Many2one(
        'res.users', 'Hiring Manager',
        related='request_id.user_id',
        store=False,
    )
    request_state = fields.Char(
        compute='_compute_request_state',
        string='Request State',
    )
    current_round_id = fields.Many2one(
        'recruitment.interview.round',
        compute='_compute_current_round',
        string='Current Round',
    )
    current_round_state = fields.Char(
        compute='_compute_current_round',
        string='Current Round State',
    )
    is_hr_admin = fields.Boolean(compute='_compute_user_role')
    is_hiring_manager = fields.Boolean(compute='_compute_user_role')
    is_management = fields.Boolean(compute='_compute_user_role')
    # ── final approval ─────────────────────────────────────────────────────
    final_approval_ids = fields.One2many(
        'recruitment.final.approval', 'candidate_id', 'Final Approvals',
    )
    final_approval_count = fields.Integer(
        compute='_compute_final_approval_count',
        string='Final Approvals',
    )
    # ── IT onboarding ──────────────────────────────────────────────────────
    it_onboarding_ids = fields.One2many(
        'recruitment.it.onboarding', 'candidate_id', 'IT Onboarding',
    )
    it_onboarding_count = fields.Integer(
        compute='_compute_it_onboarding_count',
        string='IT Onboarding',
    )
    # True when the request's required vacancies are already filled by selected candidates
    request_vacancies_filled = fields.Boolean(
        compute='_compute_request_vacancies_filled',
        string='Request Vacancies Filled',
    )
    # Char labels used for safe readonly display of nullable Selection fields.
    total_experience_label = fields.Char(compute='_compute_selection_labels')
    relevant_experience_label = fields.Char(compute='_compute_selection_labels')
    salary_currency_label = fields.Char(compute='_compute_selection_labels')
    notice_period_label = fields.Char(compute='_compute_selection_labels')

    def _compute_final_approval_count(self):
        FinalApproval = self.env['recruitment.final.approval'].sudo()
        for rec in self:
            rec.final_approval_count = FinalApproval.search_count([('candidate_id', '=', rec.id)])

    def _compute_it_onboarding_count(self):
        ITOnboarding = self.env['recruitment.it.onboarding'].sudo()
        for rec in self:
            rec.it_onboarding_count = ITOnboarding.search_count([('candidate_id', '=', rec.id)])

    @api.depends('request_id.selected_candidate_count', 'request_id.num_vacancies')
    def _compute_request_vacancies_filled(self):
        for rec in self:
            if rec.request_id:
                rec.request_vacancies_filled = (
                    rec.request_id.selected_candidate_count >= rec.request_id.num_vacancies
                )
            else:
                rec.request_vacancies_filled = False

    @api.depends('state')
    def _compute_sort_priority(self):
        for rec in self:
            rec.sort_priority = 0 if rec.state == 'selected' else 1

    @api.constrains('email')
    def _check_email_format(self):
        pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
        for rec in self:
            if rec.email and not re.match(pattern, rec.email):
                raise ValidationError(_(
                    'Please enter a valid email address (e.g. name@example.com).'
                ))

    @api.constrains('phone')
    def _check_phone_numeric(self):
        for rec in self:
            if rec.phone:
                digits_only = re.sub(r'\s+', '', rec.phone)
                if not digits_only.isdigit():
                    raise ValidationError(_('Contact Number must contain digits only.'))
                if len(digits_only) < 7:
                    raise ValidationError(_('Contact Number must have at least 7 digits.'))

    @api.depends('request_id.state')
    def _compute_request_state(self):
        for rec in self:
            rec.request_state = rec.request_id.state or ''

    def _compute_user_role(self):
        user = self.env.user
        is_admin = user.has_group('recruitment_gk.group_recruitment_hr_admin')
        is_hm = user.has_group('recruitment_gk.group_recruitment_hiring_manager')
        is_mgmt = user.has_group('recruitment_gk.group_recruitment_management')
        for rec in self:
            rec.is_hr_admin = is_admin or is_mgmt
            rec.is_hiring_manager = is_hm or is_admin or is_mgmt
            rec.is_management = is_mgmt

    @api.depends(
        'total_experience', 'total_experience_months',
        'relevant_experience', 'relevant_experience_months',
        'salary_currency', 'notice_period',
    )  # notice_period is a Char; listed here so the label stays in sync when the field changes
    def _compute_selection_labels(self):
        exp_map = dict(self._fields['total_experience'].selection)
        exp_m_map = dict(self._fields['total_experience_months'].selection)
        rel_map = dict(self._fields['relevant_experience'].selection)
        rel_m_map = dict(self._fields['relevant_experience_months'].selection)
        curr_map = dict(self._fields['salary_currency'].selection)

        for rec in self:
            parts = [exp_map.get(rec.total_experience or '', ''),
                     exp_m_map.get(rec.total_experience_months or '', '')]
            rec.total_experience_label = ' '.join(p for p in parts if p)
            rel_parts = [rel_map.get(rec.relevant_experience or '', ''),
                         rel_m_map.get(rec.relevant_experience_months or '', '')]
            rec.relevant_experience_label = ' '.join(p for p in rel_parts if p)
            rec.salary_currency_label = curr_map.get(rec.salary_currency or '', '')
            rec.notice_period_label = rec.notice_period or ''

    @api.depends(
        'interview_ids.state',
        'interview_ids.round_result',
        'state',
    )
    def _compute_all_rounds_selected(self):
        for rec in self:
            active_rounds = rec.interview_ids.filtered(
                lambda r: r.state not in ('cancelled', 'draft')
            )
            if not active_rounds:
                rec.all_rounds_selected = False
            else:
                # All active rounds must have round_result = 'selected'
                rec.all_rounds_selected = all(
                    r.round_result == 'selected' for r in active_rounds
                )

    @api.depends('interview_ids.state')
    def _compute_all_rounds_passed(self):
        for rec in self:
            rounds = rec.interview_ids.filtered(lambda r: r.state != 'cancelled')
            if not rounds:
                rec.all_rounds_passed = False
                continue
            draft = rounds.filtered(lambda r: r.state == 'draft')
            active = rounds.filtered(lambda r: r.state != 'draft')
            # True only when no draft rounds remain and every active round was selected
            if draft or not active:
                rec.all_rounds_passed = False
            else:
                # 'passed' kept for backward-compat with older records; new flow uses 'selected'
                rec.all_rounds_passed = all(r.state in ('selected', 'passed') for r in active)

    @api.depends('interview_ids.state', 'state')
    def _compute_all_rounds_completed(self):
        for rec in self:
            # interview_completed means rounds were done but vacancies were filled by others
            if rec.state == 'interview_completed':
                rec.all_rounds_completed = True
                continue
            if rec.state != 'interview':
                rec.all_rounds_completed = False
                continue
            rounds = rec.interview_ids.filtered(lambda r: r.state != 'cancelled')
            if not rounds:
                rec.all_rounds_completed = False
            else:
                rec.all_rounds_completed = all(
                    r.state in ('completed', 'selected', 'passed') for r in rounds
                )

    interview_status_badge = fields.Char(
        compute='_compute_interview_status_badge',
        string='Interview Status',
    )

    @api.depends('all_rounds_completed', 'state')
    def _compute_interview_status_badge(self):
        for rec in self:
            if rec.state == 'interview_completed':
                rec.interview_status_badge = 'Interview Completed'
            elif rec.state == 'interview' and rec.all_rounds_completed:
                rec.interview_status_badge = 'All Rounds Completed'
            else:
                rec.interview_status_badge = ''

    @api.depends('interview_ids.state', 'interview_ids.round_order')
    def _compute_current_round(self):
        for rec in self:
            # Get the most advanced non-draft active round
            active = rec.interview_ids.filtered(
                lambda r: r.state not in ('draft', 'cancelled')
            ).sorted('round_order', reverse=True)
            latest = active[:1]
            rec.current_round_id = latest or False
            rec.current_round_state = latest.state if latest else ''

    # ── defaults & expanders ───────────────────────────────────────────────

    def _default_stage(self):
        return self.env['recruitment.stage'].search(
            [('stage_type', '=', 'new')], limit=1
        )

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([], order='sequence asc')

    @api.depends('interview_ids')
    def _compute_interview_count(self):
        for rec in self:
            rec.interview_count = len(rec.interview_ids)

    # ── email helper (delegates to recruitment.request) ───────────────────

    def _send_template_email(self, template_xml_id, record, extra_recipients=None):
        self.env['recruitment.request']._send_template_email(
            template_xml_id, record, extra_recipients=extra_recipients
        )

    def _group_users(self, xml_id):
        return self.env['recruitment.request']._group_users(xml_id)

    # ── actions ────────────────────────────────────────────────────────────

    def action_open_final_approval(self):
        """Open existing final approval record or create a new one for this selected candidate."""
        self.ensure_one()
        if self.final_approval_ids:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Final Approval Details'),
                'res_model': 'recruitment.final.approval',
                'res_id': self.final_approval_ids[0].id,
                'view_mode': 'form',
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Final Approval Details'),
            'res_model': 'recruitment.final.approval',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_candidate_id': self.id},
        }

    def action_open_it_onboarding(self):
        """Open the IT Onboarding record for this candidate (readonly for non-IT users)."""
        self.ensure_one()
        record = self.it_onboarding_ids[:1]
        if not record:
            raise UserError(_('No IT Onboarding record found for this candidate.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Onboarding Details'),
            'res_model': 'recruitment.it.onboarding',
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_set_to_new(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reset Candidate to New'),
            'res_model': 'recruitment.set.to.new.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    def action_submit(self):
        new_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'new')], limit=1
        )
        for rec in self:
            rec.state = 'new'
            if new_stage:
                rec.stage_id = new_stage

    def action_move_to_manager_review(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send to Manager'),
            'res_model': 'recruitment.send.manager.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
                'default_manager_id': self.request_id.user_id.id,
            },
        }

    def action_hm_select_candidate(self):
        for rec in self:
            rec.state = 'hm_approved'
            hr_admins = rec._group_users('group_recruitment_hr_admin')
            partners = hr_admins.mapped('partner_id').filtered('email')
            if partners:
                rec.message_post(
                    body=Markup('Candidate <b>%s</b> has been <b>Selected</b> by the Hiring Manager.') % escape(rec.name),
                    subtype_xmlid='mail.mt_note',
                )
            rec._send_template_email(
                'email_template_hm_candidate_selected', rec, extra_recipients=hr_admins
            )

    def _check_hr_admin(self):
        if not (self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
                or self.env.user.has_group('recruitment_gk.group_recruitment_management')):
            raise UserError(_('Only HR Admin can perform this action.'))

    def action_approve_for_interview(self):
        """Open the Interview Round Configuration wizard with default rounds pre-filled."""
        self.ensure_one()
        self._check_hr_admin()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interview Round Configuration'),
            'res_model': 'recruitment.schedule.interview.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    def action_reschedule_round(self):
        """HR Admin reschedules the current round."""
        self.ensure_one()
        current = self.current_round_id
        if not current:
            raise UserError(_('No interview round found to reschedule.'))
        new_round = self.env['recruitment.interview.round'].create({
            'candidate_id': self.id,
            'stage_id': current.stage_id.id,
            'name': current.name,
            'round_order': current.round_order,
            'state': 'scheduled',
        })
        self.message_post(
            body=Markup('Interview round rescheduled: <b>%s</b>') % escape(new_round.name),
            subtype_xmlid='mail.mt_note',
        )
        return {
            'type': 'ir.actions.act_window',
            'name': new_round.name,
            'res_model': 'recruitment.interview.round',
            'res_id': new_round.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_move_to_next_round(self):
        """HR Admin opens the next pre-created draft round."""
        self.ensure_one()
        current = self.current_round_id
        if not current:
            raise UserError(_('No interview round found.'))

        next_round = self.interview_ids.filtered(
            lambda r: r.state == 'draft' and r.round_order > current.round_order
        ).sorted('round_order')[:1]

        if next_round:
            if next_round.stage_id:
                self.stage_id = next_round.stage_id
            self.message_post(
                body=Markup('Moved to next interview round: <b>%s</b>') % escape(next_round.name),
                subtype_xmlid='mail.mt_note',
            )
            return {
                'type': 'ir.actions.act_window',
                'name': next_round.name,
                'res_model': 'recruitment.interview.round',
                'res_id': next_round.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            self.message_post(
                body=Markup('All interview rounds completed. Candidate is ready for final decision.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_reject(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Candidate'),
            'res_model': 'recruitment.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_candidate_id': self.id,
                'candidate_previous_state': self.state,
            },
        }

    def action_mark_selected(self):
        selected_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'selected')], limit=1
        )
        for rec in self:
            rec.state = 'selected'
            if selected_stage:
                rec.stage_id = selected_stage
            if rec.request_id:
                request = rec.request_id
                # Flush so the new state is visible in the database before counting
                rec.flush_recordset(['state'])
                selected_count = self.env['recruitment.candidate'].search_count([
                    ('request_id', '=', request.id),
                    ('state', '=', 'selected'),
                ])
                request.message_post(
                    body=Markup(
                        'Candidate <b>%s</b> has been selected. '
                        '(%d / %d vacancies filled)'
                    ) % (escape(rec.name), selected_count, request.num_vacancies),
                    subtype_xmlid='mail.mt_note',
                )
                if selected_count >= request.num_vacancies:
                    if request.state not in ('selected', 'rejected'):
                        request.state = 'selected'
                    # Move all remaining hm_approved/interview candidates to interview_completed
                    others = self.env['recruitment.candidate'].search([
                        ('request_id', '=', request.id),
                        ('state', 'in', ['hm_approved', 'interview']),
                        ('id', '!=', rec.id),
                    ])
                    if others:
                        others.write({'state': 'interview_completed'})
            # Notify only the specific Hiring Manager for this request (req. 5)
            specific_hm = rec.request_id.user_id if rec.request_id else self.env['res.users'].browse()
            rec._send_template_email(
                'email_template_candidate_selected', rec,
                extra_recipients=specific_hm or rec._group_users('group_recruitment_hr_admin'),
            )

    def action_reset_to_draft_full(self):
        """Reset selected candidate to Draft and delete all interview rounds."""
        self.ensure_one()
        self.interview_ids.unlink()
        draft_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'draft')], limit=1
        )
        self.write({
            'state': 'draft',
            'stage_id': draft_stage.id if draft_stage else False,
        })
        self.message_post(
            body=_('Candidate reset to Draft. All interview rounds removed.'),
            subtype_xmlid='mail.mt_note',
        )

    def action_open_send_hm_wizard(self):
        """Open wizard to send this candidate to fill a vacancy in a Hiring Manager request."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send to Hiring Manager'),
            'res_model': 'recruitment.candidate.send.hm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_candidate_id': self.id},
        }

    def action_view_interviews(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Interview Rounds'),
            'res_model': 'recruitment.interview.round',
            'view_mode': 'list,form',
            'domain': [('candidate_id', '=', self.id)],
            'context': {
                'default_candidate_id': self.id,
                'create': False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        draft_stage = self.env['recruitment.stage'].search(
            [('stage_type', '=', 'draft')], limit=1
        )
        for rec in records:
            rec.state = 'draft'
            if draft_stage:
                rec.stage_id = draft_stage
        return records
