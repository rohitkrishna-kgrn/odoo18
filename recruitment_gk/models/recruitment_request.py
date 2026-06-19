import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)


class RecruitmentRequest(models.Model):
    _name = 'recruitment.request'
    _description = 'Recruitment Request'
    _inherit = ['recruitment.gk.base', 'mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char('Request Number', readonly=True, default='New', copy=False)
    department_id = fields.Many2one('hr.department', 'Department', tracking=True)
    job_id = fields.Many2one('hr.job', 'Position', required=True, tracking=True)
    job_title = fields.Char('Position', compute='_compute_job_title', store=True, tracking=True)
    available_job_ids = fields.Many2many('hr.job', compute='_compute_available_job_ids')
    reporting_manager_id = fields.Many2one('hr.employee', 'Reporting Manager', tracking=True)
    num_vacancies = fields.Integer('Number of Vacancies', default=1, tracking=True)
    employment_type = fields.Selection([
        ('permanent', 'Permanent'),
        ('contract', 'Contract'),
        ('temporary', 'Temporary'),
        ('internship', 'Internship'),
    ], 'Employment Type', required=True, default='permanent', tracking=True)
    job_description = fields.Text('Job Description', required=True)
    required_skills = fields.Text('Required Skills', required=True)
    experience_required = fields.Char('Experience Required')
    education_requirements = fields.Char('Education Requirements')
    salary_currency = fields.Selection([
        ('aed', 'AED – UAE Dirham'),
        ('inr', 'INR – Indian Rupees'),
    ], string='Salary Currency', default='aed', tracking=True)
    salary_range_min = fields.Float('Min Salary')
    salary_range_max = fields.Float('Max Salary')
    preferred_joining_date = fields.Date('Preferred Joining Date')
    business_justification = fields.Text('Business Justification')
    priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ], 'Priority', default='medium', tracking=True)
    other_notes = fields.Text('Other Notes')
    state = fields.Selection([
        ('draft', 'New'),
        ('submitted', 'Submitted to HR'),
        ('hr_review', 'HR Review'),
        ('in_progress', 'In Progress'),
        ('interview', 'Interview Process'),
        ('selected', 'Selected'),
        ('rejected', 'Rejected'),
        ('closed', 'Closed'),
    ], 'Status', default='draft', tracking=True, copy=False)

    user_id = fields.Many2one(
        'res.users', 'Hiring Manager',
        default=lambda self: self.env.user,
        tracking=True,
    )
    candidate_ids = fields.One2many('recruitment.candidate', 'request_id', 'Candidates')
    # Filtered view: candidates who completed all interview rounds (ready for final selection)
    finalized_candidate_ids = fields.One2many(
        'recruitment.candidate', 'request_id',
        domain=[('all_rounds_completed', '=', True)],
        string='All Rounds Cleared',
    )
    candidate_count = fields.Integer(
        'Candidates',
        compute='_compute_candidate_count',
        store=True,
        aggregator='sum',
    )
    selected_candidate_count = fields.Integer(
        compute='_compute_selected_candidate_count',
        store=True,
        string='Selected Candidates',
    )
    vacancies_progress = fields.Char(
        compute='_compute_vacancies_progress',
        string='Vacancies Filled',
    )
    needs_more_candidates = fields.Boolean(
        compute='_compute_needs_more_candidates',
        string='Needs More Candidates',
    )
    rejection_remark = fields.Text('Rejection Remark')
    candidates_shared = fields.Boolean('Candidates Shared', default=False, tracking=True)
    show_candidates_button = fields.Boolean(compute='_compute_show_candidates_button')
    is_hr_admin = fields.Boolean(compute='_compute_user_role')
    is_hiring_manager = fields.Boolean(compute='_compute_user_role')
    is_management = fields.Boolean(compute='_compute_user_role')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.depends('job_id')
    def _compute_job_title(self):
        for rec in self:
            rec.job_title = rec.job_id.name or ''

    @api.depends('department_id')
    def _compute_available_job_ids(self):
        for rec in self:
            if rec.department_id:
                # Positions held by current employees in this department
                employee_jobs = self.env['hr.employee'].search([
                    ('department_id', '=', rec.department_id.id),
                    ('job_id', '!=', False),
                ]).mapped('job_id')
                # Positions explicitly linked to this department
                dept_jobs = self.env['hr.job'].search([
                    ('department_id', '=', rec.department_id.id)
                ])
                rec.available_job_ids = employee_jobs | dept_jobs
            else:
                rec.available_job_ids = self.env['hr.job'].search([])

    @api.constrains('num_vacancies')
    def _check_num_vacancies(self):
        for rec in self:
            if not rec.num_vacancies or rec.num_vacancies < 1:
                raise ValidationError(_(
                    'Number of Vacancies must be at least 1. '
                    'Please enter a valid number before saving.'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    @api.depends('candidate_ids')
    def _compute_candidate_count(self):
        for rec in self:
            rec.candidate_count = len(rec.candidate_ids)

    @api.depends('candidate_ids.state')
    def _compute_selected_candidate_count(self):
        for rec in self:
            rec.selected_candidate_count = len(
                rec.candidate_ids.filtered(lambda c: c.state == 'selected')
            )

    @api.depends('selected_candidate_count', 'num_vacancies')
    def _compute_vacancies_progress(self):
        for rec in self:
            rec.vacancies_progress = '%d / %d' % (rec.selected_candidate_count, rec.num_vacancies)

    @api.depends('candidate_ids.state', 'candidate_ids.all_rounds_completed', 'num_vacancies', 'selected_candidate_count', 'state')
    def _compute_needs_more_candidates(self):
        for rec in self:
            if rec.state in ('selected', 'closed'):
                # All vacancies filled — hide the Share button entirely
                rec.needs_more_candidates = False
            else:
                finalized = rec.candidate_ids.filtered(
                    lambda c: c.all_rounds_completed and c.state not in ('rejected',)
                )
                rec.needs_more_candidates = (
                    rec.selected_candidate_count < rec.num_vacancies
                    and len(finalized) < rec.num_vacancies
                )

    def _compute_show_candidates_button(self):
        is_admin = self.env.user.has_group('recruitment_gk.group_recruitment_hr_admin')
        is_mgmt = self.env.user.has_group('recruitment_gk.group_recruitment_management')
        for rec in self:
            rec.show_candidates_button = is_admin or is_mgmt or rec.candidates_shared

    def _compute_user_role(self):
        user = self.env.user
        is_admin = user.has_group('recruitment_gk.group_recruitment_hr_admin')
        is_hm = user.has_group('recruitment_gk.group_recruitment_hiring_manager')
        is_mgmt = user.has_group('recruitment_gk.group_recruitment_management')
        for rec in self:
            rec.is_hr_admin = is_admin or is_mgmt
            # HR Admin and Management can also act as Hiring Managers for their own requests;
            # combined HR Admin + HM users get the full union of both roles.
            rec.is_hiring_manager = is_hm or is_admin or is_mgmt
            rec.is_management = is_mgmt

    # ── write override: vacancy-increase validation & auto-restore ────────

    def write(self, vals):
        # Capture old vacancy counts before the write so we can compare after.
        old_vacancies = {}
        if 'num_vacancies' in vals:
            new_vacancies = vals['num_vacancies']
            for rec in self:
                if new_vacancies <= rec.num_vacancies:
                    continue  # decrease or no change — no special handling needed
                if rec.state not in ('interview', 'selected'):
                    continue  # only guard active hiring states
                increase = new_vacancies - rec.num_vacancies
                interview_completed = rec.candidate_ids.filtered(
                    lambda c: c.state == 'interview_completed'
                )
                avail = len(interview_completed)
                if avail < increase:
                    raise UserError(_(
                        'Cannot increase vacancies by %d: only %d candidate(s) are in '
                        '"Interview Completed" state.\n'
                        'Please share %d more candidate(s) first using '
                        '"Share More Candidates".'
                    ) % (increase, avail, increase - avail))
                # Record old value so we can trigger restoration after super().write
                old_vacancies[rec.id] = rec.num_vacancies

        result = super().write(vals)

        # After a successful vacancy increase, restore interview_completed
        # candidates to interview and move the request back if it was selected.
        for rec_id, old in old_vacancies.items():
            rec = self.browse(rec_id)
            if rec.num_vacancies <= old:
                continue
            to_restore = rec.candidate_ids.filtered(lambda c: c.state == 'interview_completed')
            if to_restore:
                to_restore.write({'state': 'interview'})
            if rec.state == 'selected':
                rec.write({'state': 'interview'})

        return result

    # ── email helpers ──────────────────────────────────────────────────────

    def _group_users(self, xml_id):
        group = self.env.ref('recruitment_gk.%s' % xml_id, raise_if_not_found=False)
        return group.users if group else self.env['res.users'].browse()

    def _send_template_email(self, template_xml_id, record, extra_recipients=None):
        template = self.env.ref(
            'recruitment_gk.%s' % template_xml_id, raise_if_not_found=False
        )
        if not template:
            _logger.warning('recruitment_gk: template %s not found', template_xml_id)
            return
        email_values = {'auto_delete': False}
        if extra_recipients:
            partners = extra_recipients.mapped('partner_id').filtered('email')
            if not partners:
                _logger.warning(
                    'recruitment_gk: skipping %s – none of the %d recipient(s) have an email configured',
                    template_xml_id, len(extra_recipients),
                )
                return
            email_values.update({
                'recipient_ids': [(4, p.id) for p in partners],
                'email_to': '',
            })
        mail_id = template.send_mail(
            record.id,
            force_send=True,
            raise_exception=False,
            email_values=email_values,
        )
        if not mail_id:
            _logger.warning(
                'recruitment_gk: send_mail returned falsy for %s on %s/%s',
                template_xml_id, record._name, record.id,
            )

    # ── state transitions ──────────────────────────────────────────────────

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only Draft requests can be submitted.'))
            if rec.name == 'New':
                rec.name = (
                    self.env['ir.sequence'].next_by_code('recruitment.request') or 'New'
                )
            rec.state = 'submitted'
            hr_admins = rec._group_users('group_recruitment_hr_admin')
            rec._send_template_email(
                'email_template_request_submitted', rec, extra_recipients=hr_admins
            )

    def action_start_review(self):
        self.write({'state': 'hr_review'})

    def action_in_progress(self):
        for rec in self:
            if not rec.candidates_shared:
                raise UserError(_(
                    'Please select and share candidates before moving to In Progress.'
                ))
        self.write({'state': 'in_progress'})

    def action_interview_process(self):
        self.write({'state': 'interview'})

    def action_mark_request_selected(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Final Candidate Selection'),
            'res_model': 'recruitment.final.selection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_reset_draft(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reset Request to New'),
            'res_model': 'recruitment.request.reset.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_reject_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Request'),
            'res_model': 'recruitment.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    # ── share candidates wizard ────────────────────────────────────────────

    def action_share_candidates(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Share Candidates'),
            'res_model': 'recruitment.share.candidates.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_request_id': self.id,
                'default_hiring_manager_id': self.user_id.id,
            },
        }

    def action_share_more_candidates(self):
        """HR Admin shares additional candidates when vacancies are not yet filled."""
        return self.action_share_candidates()

    # ── smart button ───────────────────────────────────────────────────────

    def action_close_request(self):
        for rec in self:
            if rec.state != 'selected':
                raise UserError(_('Only requests in the Selected state (all vacancies filled) can be closed.'))
            rec.state = 'closed'
            rec.message_post(
                body=_('Recruitment request closed. All vacancies have been filled.'),
                subtype_xmlid='mail.mt_note',
            )

    def action_view_candidates(self):
        domain = [('request_id', '=', self.id)]
        user = self.env.user
        is_hm = user.has_group('recruitment_gk.group_recruitment_hiring_manager')
        is_admin = user.has_group('recruitment_gk.group_recruitment_hr_admin')
        is_mgmt = user.has_group('recruitment_gk.group_recruitment_management')
        # Pure HM (no HR Admin / Management) sees only selected candidates once request is filled
        if is_hm and not is_admin and not is_mgmt and self.state == 'selected':
            domain.append(('state', '=', 'selected'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Candidates'),
            'res_model': 'recruitment.candidate',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'default_request_id': self.id, 'create': False},
        }
