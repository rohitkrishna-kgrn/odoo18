import logging
from collections import defaultdict
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from markupsafe import Markup

from odoo.tools import html_escape

from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor, leave_month_bounds

from . import tools
from .payroll_line import EDITABLE_STATES, SYSTEM_CTX
from .perf import scoped

_logger = logging.getLogger(__name__)

STATES = [
    ('draft', 'Draft'),
    ('calculated', 'Calculated'),
    ('submitted', 'Submitted'),
    ('resubmit', 'Resubmission Requested'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
    ('cancel', 'Cancelled'),
]


def _default_month(self):
    return str(leave_month_anchor(fields.Date.context_today(self)).month)


def _default_year(self):
    return str(leave_month_anchor(fields.Date.context_today(self)).year)


class PayrollCountryBatch(models.Model):
    _name = 'payroll.country.batch'
    _description = 'Country Payroll Batch'
    _inherit = ['payroll.no.mail.chatter', 'mail.thread', 'mail.activity.mixin']     # guard first
    _order = 'year desc, month_num desc, id desc'

    name = fields.Char(string='Payroll Reference', readonly=True, copy=False, default='/', tracking=True)
    payroll_country_id = fields.Many2one(
        'payroll.country', string='Payroll', required=True, tracking=True, index=True,
        default=lambda self: self.env.context.get('default_payroll_country_id'))
    country_id = fields.Many2one(related='payroll_country_id.country_id', store=True, string='Country', index=True)
    country_code = fields.Char(related='payroll_country_id.country_code')
    pf_esi_enabled = fields.Boolean(compute='_compute_pf_esi_enabled',
                                    help="PF / ESI columns: India payroll only.")
    month = fields.Selection(tools.MONTHS, string='Month', required=True, default=_default_month, tracking=True)
    year = fields.Selection(tools.YEARS, string='Year', required=True, default=_default_year, tracking=True)
    month_num = fields.Integer(compute='_compute_period', store=True)
    date_from = fields.Date(string='Period From', compute='_compute_period', store=True)
    date_to = fields.Date(string='Period To', compute='_compute_period', store=True)
    period_label = fields.Char(string='Payroll Period', compute='_compute_period', store=True)
    company_ids = fields.Many2many(
        'res.company', 'payroll_country_batch_company_rel', 'batch_id', 'company_id', string='Companies',
        tracking=True,
        groups='om_hr_payroll.group_hr_payroll_user')
    allowed_company_ids = fields.Many2many(
        'res.company', compute='_compute_allowed_company_ids',
        groups='om_hr_payroll.group_hr_payroll_user')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True, tracking=True,
        default=lambda self: self.env.company,
        help="The company this payroll was created in (the active company); payroll emails are sent "
             "from it. Approval is done by the Payroll Admins.")
    user_company_ids = fields.Many2many('res.company', compute='_compute_user_company_ids')
    company_names = fields.Char(string='Company Names', compute='_compute_company_data', store=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_company_data', store=True)
    state = fields.Selection(STATES, string='Status', default='draft', required=True, tracking=True, index=True)

    line_ids = fields.One2many('payroll.country.line', 'batch_id', string='Payroll Lines')
    distribution_line_ids = fields.One2many('payroll.country.line', 'batch_id', string='Payslip Distribution')
    excluded_ids = fields.One2many('payroll.country.excluded', 'batch_id', string='Not Fetched')
    notify_log_ids = fields.One2many('payroll.country.notify.log', 'batch_id', string='Notification History')
    change_log_ids = fields.One2many('payroll.country.change.log', 'batch_id', string='Manual Changes')
    send_log_ids = fields.One2many('payroll.payslip.send.log', 'batch_id', string='Payslip Email History')

    employee_count = fields.Integer(string='Total Employees', compute='_compute_totals', store=True)
    total_gross = fields.Monetary(string='Total Gross Salary', compute='_compute_totals', store=True)
    total_deductions = fields.Monetary(string='Total Deductions', compute='_compute_totals', store=True)
    total_net = fields.Monetary(string='Total Net Salary', compute='_compute_totals', store=True)
    error_count = fields.Integer(string='Errors', compute='_compute_totals', store=True)
    warning_count = fields.Integer(string='Warnings', compute='_compute_totals', store=True)

    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False, tracking=True)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True, copy=False)
    submission_round = fields.Integer(string='Submissions', readonly=True, copy=False, default=0)
    approver_user_ids = fields.Many2many(
        'res.users', 'payroll_country_batch_approver_rel', 'batch_id', 'user_id', string='Approvers',
        readonly=True, copy=False,
        help="The Payroll Admins (Settings > Users > Payroll: Admin) the batch was submitted to.")
    approved_user_ids = fields.Many2many(
        'res.users', 'payroll_country_batch_approved_rel', 'batch_id', 'user_id', string='Approved So Far',
        readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False, tracking=True)
    approved_date = fields.Datetime(string='Approved On', readonly=True, copy=False)
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Payslip Batch', readonly=True, copy=False,
                                     help="Payroll > Payslip Batches entry created when the payroll is approved.")
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False, tracking=True)
    rejected_by = fields.Many2one('res.users', string='Rejected By', readonly=True, copy=False)
    rejected_date = fields.Datetime(string='Rejected On', readonly=True, copy=False)
    resubmit_reason = fields.Text(string='Resubmission Reason', readonly=True, copy=False, tracking=True)
    resubmit_by = fields.Many2one('res.users', string='Resubmission Asked By', readonly=True, copy=False)
    resubmit_date = fields.Datetime(string='Resubmission Asked On', readonly=True, copy=False)

    can_approve = fields.Boolean(compute='_compute_user_flags')
    is_officer = fields.Boolean(compute='_compute_user_flags')
    email_pending_count = fields.Integer(string='Not Sent', compute='_compute_email_counts')
    email_sent_count = fields.Integer(string='Sent', compute='_compute_email_counts')
    email_failed_count = fields.Integer(string='Failed', compute='_compute_email_counts')

    # ------------------------------------------------------------ computes
    @api.depends('month', 'year')
    def _compute_period(self):
        for batch in self:
            if batch.month and batch.year:
                anchor = fields.Date.to_date('%s-%02d-01' % (batch.year, int(batch.month)))
                start, end = leave_month_bounds(anchor)
                batch.month_num = int(batch.month)
                batch.date_from, batch.date_to = start, end
                batch.period_label = '%s %s (%s - %s)' % (tools.month_label(batch.month), batch.year,
                                                         start.strftime('%d %b'), end.strftime('%d %b'))
            else:
                batch.month_num = 0
                batch.date_from = batch.date_to = False
                batch.period_label = False

    @api.depends('payroll_country_id.leave_location')
    def _compute_pf_esi_enabled(self):
        for batch in self:
            batch.pf_esi_enabled = batch.payroll_country_id.leave_location == 'india'

    @api.depends('payroll_country_id', 'date_from', 'date_to')
    def _compute_allowed_company_ids(self):
        for batch in self:
            batch.allowed_company_ids = batch.payroll_country_id._country_companies(
                batch.date_from, batch.date_to) if batch.payroll_country_id else False

    @api.depends('company_ids')
    def _compute_company_data(self):
        for batch in self:
            companies = batch.sudo().company_ids
            batch.company_names = ', '.join(companies.mapped('name')) or False
            batch.currency_id = companies[:1].currency_id or self.env.company.currency_id

    @api.depends_context('uid')
    def _compute_user_company_ids(self):
        for batch in self:
            batch.user_company_ids = self.env.user.company_ids

    @api.depends('line_ids.gross', 'line_ids.total_deductions', 'line_ids.net', 'line_ids.validation_status',
                 'line_ids.state')
    def _compute_totals(self):
        for batch in self:
            lines = batch.line_ids.filtered(lambda l: l.state != 'cancel')
            batch.employee_count = len(lines)
            batch.total_gross = sum(lines.mapped('gross'))
            batch.total_deductions = sum(lines.mapped('total_deductions'))
            batch.total_net = sum(lines.mapped('net'))
            batch.error_count = len(lines.filtered(lambda l: l.validation_status == 'error'))
            batch.warning_count = len(lines.filtered(lambda l: l.validation_status == 'warning'))

    @api.depends_context('uid')
    @api.depends('state', 'approver_user_ids', 'approved_user_ids', 'submitted_by')
    def _compute_user_flags(self):
        user = self.env.user
        manager = user._is_payroll_manager()
        allowed = user._payroll_allowed_countries()
        for batch in self:
            batch.is_officer = manager or (user._is_payroll_officer() and batch.country_id in allowed)
            batch.can_approve = batch.state == 'submitted' and batch._approver_problem(user) is None

    def _compute_email_counts(self):
        for batch in self:
            lines = batch.line_ids.filtered(lambda l: l.state == 'approved')
            batch.email_sent_count = len(lines.filtered(lambda l: l.email_status == 'sent'))
            batch.email_failed_count = len(lines.filtered(lambda l: l.email_status in ('failed', 'no_email')))
            batch.email_pending_count = len(lines.filtered(lambda l: l.email_status != 'sent'))

    @api.depends('name', 'payroll_country_id', 'month', 'year')
    def _compute_display_name(self):
        for batch in self:
            batch.display_name = '%s - %s %s %s' % (
                batch.name or '/', batch.country_id.name or '', tools.month_label(batch.month), batch.year or '')

    # ------------------------------------------------------------ constraints / ORM
    @api.constrains('company_ids', 'payroll_country_id')
    def _check_companies(self):
        for batch in self.sudo():
            wrong = batch.company_ids.filtered(lambda c: c.partner_id.country_id != batch.country_id)
            if wrong:
                raise ValidationError(_("%(companies)s is not registered in %(country)s - pick companies of the "
                                        "payroll country only.", companies=', '.join(wrong.mapped('name')),
                                        country=batch.country_id.name))
            if len(batch.company_ids.currency_id) > 1:
                raise ValidationError(_("The selected companies use different currencies; create one batch per currency."))

    @api.onchange('payroll_country_id', 'month', 'year')
    def _onchange_payroll_country(self):
        """Companies follow the payroll country and period automatically."""
        for batch in self:
            if batch.line_ids:
                continue
            batch.company_ids = batch.payroll_country_id._country_companies(
                batch.date_from, batch.date_to) if batch.payroll_country_id else False

    @api.model_create_multi
    @scoped
    def create(self, vals_list):
        batches = super().create(vals_list)
        for batch in batches:
            if batch.name in (False, '/'):
                batch._system_write({'name': batch._reference_name()})
        for batch in batches:
            batch._check_officer_rights()
            if not batch.sudo().company_ids:
                companies = batch.payroll_country_id._country_companies(batch.date_from, batch.date_to)
                if not companies:
                    raise UserError(_("No contract of a %(loc)s employee is with a company in %(country)s for "
                                      "%(period)s.", loc=batch.payroll_country_id.leave_location or '',
                                      country=batch.country_id.name, period=batch.period_label))
                batch.company_ids = companies
        if not self.env.context.get('payroll_no_autofetch'):
            # everything ready at once: employees fetched and the payroll calculated on save
            for batch in batches:
                batch.action_fetch_employees()
        return batches

    def _reference_name(self):
        """PAYROLL/<country code>/<year>/<month>, e.g. PAYROLL/UAE/2026/2 for February 2026.
        A second payroll of the same country and month gets -2, -3..."""
        self.ensure_one()
        cfg = self.payroll_country_id
        code = cfg.reference_code or cfg.country_code or 'XX'
        base = 'PAYROLL/%s/%s/%s' % (code, self.year, int(self.month))
        taken = set(self.sudo().with_context(active_test=False).search(
            [('name', '=like', base + '%'), ('id', '!=', self.id)]).mapped('name'))
        name, n = base, 1
        while name in taken:
            n += 1
            name = '%s-%s' % (base, n)
        return name

    def write(self, vals):
        if {'payroll_country_id', 'month', 'year'} & set(vals) and not self.env.context.get(SYSTEM_CTX):
            for batch in self:
                if batch.line_ids:
                    raise UserError(_("Country, month and year cannot change once employees are fetched. "
                                      "Cancel this batch and create a new one."))
        if {'company_ids', 'company_id'} & set(vals) and not self.env.context.get(SYSTEM_CTX):
            for batch in self:
                if batch.state not in EDITABLE_STATES:
                    raise UserError(_("Companies cannot change after submission."))
        res = super().write(vals)
        if 'company_ids' in vals and not self.env.context.get(SYSTEM_CTX) \
                and not self.env.context.get('payroll_no_autofetch'):
            for batch in self.filtered(lambda b: b.line_ids and b.state in EDITABLE_STATES):
                batch.action_fetch_employees()      # other companies -> other employees, recalculated
        if {'payroll_country_id', 'month', 'year'} & set(vals):
            for batch in self.filtered(lambda b: b.state in EDITABLE_STATES):
                name = batch._reference_name()
                if name != batch.name:
                    batch._system_write({'name': name})
        return res

    def unlink(self):
        for batch in self:
            if batch.state not in ('draft', 'cancel'):
                raise UserError(_("Only draft or cancelled payroll batches can be deleted (%s).") % batch.name)
            batch._check_officer_rights()
        slips = self.sudo().line_ids.payslip_id.filtered(lambda s: s.state in ('draft', 'cancel'))
        slips.unlink()
        return super().unlink()

    # ------------------------------------------------------------ rights
    def _check_officer_rights(self):
        user = self.env.user
        if self.env.su or user._is_payroll_manager():
            return
        allowed = user._payroll_allowed_countries()
        for batch in self:
            if not user._is_payroll_officer() or batch.country_id not in allowed:
                raise AccessError(_("Only a Payroll Officer whose Leave Location is %s (or a Payroll Manager) "
                                    "can do this.") % (batch.payroll_country_id.leave_location or batch.country_id.name))

    def _same_month_payslip_domain(self):
        """Payslips of the same payroll month. A payslip belongs to the month its
        end date falls in: old calendar payslips (1 Jan - 31 Jan) and 26th-25th ones
        (26 Dec - 25 Jan) are both January. Plain date overlap would wrongly make the
        31 Jan payslip a duplicate of February (26 Jan - 25 Feb)."""
        self.ensure_one()
        first = date(int(self.year), int(self.month), 1)
        return [('date_to', '>=', first), ('date_to', '<=', first + relativedelta(months=1, days=-1))]

    def _check_editable(self):
        for batch in self:
            if batch.state not in EDITABLE_STATES:
                raise UserError(_("%s is %s - it can no longer be changed.")
                                % (batch.name, dict(STATES)[batch.state]))

    def _system_write(self, vals):
        return self.sudo().with_context(**{SYSTEM_CTX: True}).write(vals)

    # ------------------------------------------------------------ fetch
    def _eligible_contracts(self):
        """{employee: contract} eligible for the period + [(employee, contract, reason)] not fetched.
        Employee -> Contract -> Company: the paying company is the contract's company."""
        self.ensure_one()
        companies = self.sudo().company_ids
        Contract = self.env['hr.contract'].sudo()
        contracts = Contract.search([
            ('company_id', 'in', companies.ids),
            ('state', 'in', ('open', 'close', 'draft')),
            ('date_start', '<=', self.date_to),
            '|', ('date_end', '=', False), ('date_end', '>=', self.date_from),
        ])
        by_employee = defaultdict(lambda: Contract.browse())
        for contract in contracts:
            by_employee[contract.employee_id] |= contract
        eligible, excluded = {}, []
        Line = self.env['payroll.country.line'].sudo()
        Payslip = self.env['hr.payslip'].sudo()
        own_slips = self.sudo().line_ids.payslip_id
        period_key = '%s-%02d' % (self.year, int(self.month))
        for employee, emp_contracts in by_employee.items():
            running = emp_contracts.filtered(lambda c: c.state in ('open', 'close'))
            if not running:
                excluded.append((employee, emp_contracts[:1], _("Contract not started yet (status New)")))
                continue
            contract = sorted(running, key=lambda c: (c.state == 'open', c.date_start), reverse=True)[0]
            location = self.payroll_country_id.leave_location
            if location and employee.country_for_leave != location:
                labels = dict(employee._fields['country_for_leave']._description_selection(self.env))
                excluded.append((employee, contract, _("Leave location is %(loc)s, not %(want)s (Country For Leave "
                                                       "Model on the user)", loc=labels.get(employee.country_for_leave)
                                                       or _('not set'), want=labels.get(location, location))))
                continue
            if not employee.active:
                # archived employees are never paid here, not even for their last month
                excluded.append((employee, contract, _("Employee is archived")))
                continue
            if not employee.user_id.active:
                # only employees with an active user (Settings > Users) are in payroll
                excluded.append((employee, contract, _("User is archived") if employee.user_id
                                 else _("No user linked to the employee")))
                continue
            start = max(contract.date_start, self.date_from)
            end = min(contract.date_end or self.date_to, self.date_to)
            if employee.departure_date:
                end = min(end, employee.departure_date)
            if start > end:
                excluded.append((employee, contract, _("Left before the period started")))
                continue
            other = Line.search([('employee_id', '=', employee.id), ('company_id', '=', contract.company_id.id),
                                 ('period_key', '=', period_key), ('is_live', '=', True),
                                 ('batch_id', '!=', self.id)], limit=1)
            if other:
                excluded.append((employee, contract, _("Already in payroll batch %s") % other.batch_id.name))
                continue
            paid = Payslip.search([('employee_id', '=', employee.id), ('state', '=', 'done'),
                                   ('credit_note', '=', False), ('id', 'not in', own_slips.ids),
                                   ] + self._same_month_payslip_domain(), limit=1)
            if paid:
                excluded.append((employee, contract, _("Already paid in Payroll: %s (Done)") % (paid.number or paid.name)))
                continue
            eligible[employee] = contract
        # employees of these companies with no contract in the period at all
        others = self.env['hr.employee'].sudo().search([
            ('company_id', 'in', companies.ids), ('id', 'not in', [e.id for e in by_employee])])
        for employee in others:
            excluded.append((employee, Contract.browse(),
                             _("User is archived (contract archived)") if employee.user_id and not employee.user_id.active
                             else _("No contract with these companies in the period")))
        return eligible, excluded

    @api.model
    def _drop_archived_employees(self, employees, reason=None):
        """Archived employees (or employees whose user was archived) leave every open batch
        at once (their draft payslip too) and are listed under Not Fetched; submitted /
        approved batches are left as they are."""
        reason = reason or _("Employee is archived")
        lines = self.env['payroll.country.line'].sudo().search([
            ('employee_id', 'in', employees.ids), ('batch_state', 'in', EDITABLE_STATES)])
        for batch in lines.batch_id:
            gone = lines.filtered(lambda l: l.batch_id == batch)
            batch._system_write({'excluded_ids': [(0, 0, {
                'employee_id': line.employee_id.id,
                'employee_name': line.employee_name or line.employee_id.name,
                'company_name': line.company_name or line.company_id.name,
                'contract_ref': line.contract_ref or False,
                'reason': reason,
            }) for line in gone]})
            names = ', '.join(gone.mapped('employee_name'))
            gone.payslip_id.filtered(lambda s: s.state == 'draft').unlink()
            gone.unlink()
            batch._log(body=_("Removed from this payroll (%(reason)s): %(names)s", reason=reason, names=names))
        return True

    @scoped
    def action_fetch_employees(self):
        self.ensure_one()
        self._check_officer_rights()
        self._check_editable()
        eligible, excluded = self._eligible_contracts()
        lines = self.sudo().line_ids
        removed = lines.filtered(lambda l: l.employee_id not in eligible)
        if removed:
            removed.payslip_id.filtered(lambda s: s.state == 'draft').unlink()
            removed.unlink()
        Line = self.env['payroll.country.line'].sudo()
        existing = {l.employee_id: l for l in self.sudo().line_ids}
        new_vals = []
        for employee, contract in eligible.items():
            line = existing.get(employee)
            vals = {'contract_id': contract.id, 'company_id': contract.company_id.id}
            if line:
                if line.contract_id != contract or line.company_id != contract.company_id:
                    line._system_write(vals)
            else:
                new_vals.append(dict(vals, batch_id=self.id, employee_id=employee.id,
                                     pf_esi_entry=self.payroll_country_id.pf_esi_mode,
                                     employee_name=employee.name, state='draft'))
        if new_vals:
            Line.with_context(**{SYSTEM_CTX: True}, mail_create_nolog=True, tracking_disable=True).create(new_vals)
        self._system_write({'excluded_ids': [(5, 0, 0)] + [(0, 0, {
            'employee_id': emp.id,
            'employee_name': emp.name,
            'company_name': contract.company_id.name or emp.company_id.name,
            'contract_ref': contract.name or False,
            'reason': reason,
        }) for emp, contract, reason in excluded]})
        lines = self.sudo().line_ids
        lines._refresh_snapshot()
        lines._system_write({'state': 'draft'})
        # pre-complete: the payroll is calculated straight away (Recalculate re-runs it)
        self._system_write({'state': 'calculated' if lines else 'draft'})
        lines._calculate()
        lines._validate()
        self._log(body=_("Employees fetched and calculated: %(n)s in payroll, %(x)s not fetched (see Not Fetched).",
                         n=len(lines), x=len(excluded)))
        return self._notify(_("Fetch Employees"),
                            _("%(n)s employee(s) fetched and calculated (%(e)s with errors), %(x)s not fetched.",
                              n=len(lines), e=self.error_count, x=len(excluded)),
                            'danger' if self.error_count else ('success' if lines else 'warning'))

    # ------------------------------------------------------------ calculate
    @scoped
    def action_calculate(self):
        self.ensure_one()
        self._check_officer_rights()
        self._check_editable()
        lines = self.sudo().line_ids
        if not lines:
            raise UserError(_("Fetch Employees first."))
        self._system_write({'state': 'calculated'})
        lines._refresh_snapshot()
        lines._calculate()
        lines._validate()
        self._log(body=_("Payroll calculated for %s employee(s) with the Payroll salary rules.") % len(lines))
        return self._notify(_("Calculate Payroll"),
                            _("%(n)s calculated - %(e)s error(s), %(w)s warning(s).",
                              n=len(lines), e=self.error_count, w=self.warning_count),
                            'danger' if self.error_count else 'success')

    @scoped
    def action_recalculate(self):
        return self.action_calculate()

    @scoped
    def action_validate(self):
        self.ensure_one()
        self._check_officer_rights()
        self.sudo().line_ids._validate(deep=True)
        return self._notify(_("Check"), _("%(e)s error(s), %(w)s warning(s).",
                                          e=self.error_count, w=self.warning_count),
                            'danger' if self.error_count else 'success')

    # ------------------------------------------------------------ submit
    def _submission_problems(self):
        self.ensure_one()
        problems = []
        lines = self.sudo().line_ids
        if not lines:
            problems.append(_("No employees fetched."))
        eligible, _excluded = self._eligible_contracts()
        missing = [e for e in eligible if e not in lines.employee_id]
        if missing:
            problems.append(_("%(n)s eligible employee(s) are not in the batch (e.g. %(names)s) - run Fetch Employees.",
                              n=len(missing), names=', '.join(e.name for e in missing[:5])))
        not_calc = lines.filtered(lambda l: l.state == 'draft')
        if not_calc:
            problems.append(_("%s employee(s) not calculated - run Calculate Payroll.") % len(not_calc))
        lines._validate(deep=True)
        for line in lines.filtered(lambda l: l.validation_status == 'error')[:15]:
            problems.append('%s: %s' % (line.employee_name, '; '.join(
                m[7:] for m in (line.validation_message or '').split('\n') if m.startswith('ERROR: '))))
        extra = len(lines.filtered(lambda l: l.validation_status == 'error')) - 15
        if extra > 0:
            problems.append(_("... and %s more employee(s) with errors.") % extra)
        if not self.env['res.users']._payroll_approvers():
            problems.append(_("No Payroll Admin to approve it: set the company's Quotation Approver User "
                              "(it becomes Payroll Admin) or give a user Payroll access 'Admin' (Settings > Users)."))
        return problems

    @scoped
    def action_submit(self):
        self.ensure_one()
        self._check_officer_rights()
        if self.state in ('rejected', 'resubmit'):
            # sent back by the approver: recalculate first (manual changes are kept), so what is
            # submitted again always reflects the latest attendance, leave and contracts
            self.action_calculate()
        if self.state != 'calculated':
            raise UserError(_("Only a Calculated, Rejected or Resubmission Requested payroll can be submitted."))
        problems = self._submission_problems()
        if problems:
            # never raise here: the per-line check results must stay saved
            return self._notify(_("Cannot submit for approval"), '\n'.join(problems), 'danger', sticky=True)
        self._system_write({
            'state': 'submitted',
            'submitted_by': self.env.uid,
            'submitted_date': fields.Datetime.now(),
            'submission_round': self.submission_round + 1,
            'approved_user_ids': [(5, 0, 0)],
            'approved_by': False,
            'approved_date': False,
            'approver_user_ids': [(6, 0, self.env['res.users']._payroll_approvers().ids)],
        })
        self.sudo().line_ids._system_write({'state': 'submitted'})
        self._notify_approvers()
        self._log(body=_("Submitted for approval to %s.") % ', '.join(self.approver_user_ids.mapped('name')))
        return self._notify(_("Submitted"), _("Sent to %s for approval.")
                            % ', '.join(self.approver_user_ids.mapped('name')), 'success')

    def get_record_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return '%s/web#id=%s&model=payroll.country.batch&view_type=form' % (base, self.id)

    def _send_template(self, xmlid, user, kind):
        """One notification per batch / kind / submission round / user (history kept)."""
        Log = self.env['payroll.country.notify.log'].sudo()
        if Log.search_count([('batch_id', '=', self.id), ('kind', '=', kind),
                             ('round', '=', self.submission_round), ('user_id', '=', user.id)]):
            return Log.browse()
        mail = self.env['mail.mail']
        email = user.email
        if email:
            template = self.env.ref(xmlid).sudo()
            mail_id = template.with_context(payroll_recipient_name=user.name).send_mail(
                self.id, force_send=False, email_values={'email_to': email, 'recipient_ids': [], 'auto_delete': False,
                                             'model': False, 'res_id': False})     # not in the chatter
            mail = self.env['mail.mail'].sudo().browse(mail_id)
        return Log.create({'batch_id': self.id, 'kind': kind, 'round': self.submission_round,
                           'user_id': user.id, 'email_to': email or False, 'mail_id': mail.id})

    def _notify_approvers(self):
        for user in self.approver_user_ids:
            self._send_template('om_hr_payroll_extended_gk.mail_template_payroll_submitted', user, 'submitted')
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=_("Approve payroll %s") % self.name,
                note=_("%(country)s payroll for %(period)s is waiting for your approval.",
                       country=self.country_id.name, period=self.period_label))

    def _close_approval_activities(self, feedback):
        todo = self.env.ref('mail.mail_activity_data_todo')
        prefix = _("Approve payroll")
        activities = self.sudo().activity_ids.filtered(lambda a: a.activity_type_id == todo
                                                       and (a.summary or '').startswith(prefix))
        if activities:
            activities.action_feedback(feedback=feedback)

    # ------------------------------------------------------------ approve / reject / resubmission
    def _approver_problem(self, user):
        """None when user may decide on this submitted batch, else the reason (text).
        Only Payroll Admins decide. Four-eyes: not on your own submission, unless you are
        the only Payroll Admin (otherwise nobody could ever approve it)."""
        if not user._is_payroll_approver():
            return _("Only a Payroll Admin can approve, reject or ask for resubmission of a payroll.")
        if user == self.submitted_by and self.env['res.users']._payroll_approvers() - user:
            return _("You submitted this payroll yourself: another Payroll Admin must decide on it.")
        return None

    def _check_approver(self):
        user = self.env.user
        if self.state != 'submitted':
            raise UserError(_("Only submitted payroll can be approved, rejected or sent back for resubmission."))
        problem = self._approver_problem(user)
        if problem:
            raise AccessError(problem)

    def action_approve(self):
        self.ensure_one()
        self._check_approver()
        self._system_write({'approved_user_ids': [(4, self.env.uid)]})
        self._finalize_approval()
        return self._notify(_("Approved"), _("Payroll approved. The %s Payroll Officers and the Payroll Managers "
                                             "were notified.") % self.country_id.name, 'success')

    def _finalize_approval(self):
        lines = self.sudo().line_ids
        slips = lines.payslip_id.filtered(lambda s: s.state == 'draft')
        # Write the state directly: Payroll's action_payslip_done would email every
        # employee immediately, and payslips are sent only on explicit request.
        # Payslip numbers are given here, in payroll order, from the gap-free Payroll
        # sequence (drafts never take one), and the payslips go into a Payroll > Payslip
        # Batches entry named after this payroll, like a batch generated in Payroll.
        slips = lines.sorted(lambda l: (l.company_name or '', l.employee_name or '', l.id)).payslip_id & slips
        slips._assign_payslip_number()
        slips.write({'state': 'done'})
        self._create_payslip_run(slips)
        for line in lines:
            line._system_write({'state': 'approved',
                                'email_status': 'pending' if line.work_email else 'no_email'})
        self._system_write({'state': 'approved', 'approved_by': self.env.uid,
                            'approved_date': fields.Datetime.now()})
        self._close_approval_activities(_("Approved by %s") % self.env.user.name)
        self._log(body=_("Payroll approved by %s.") % self.env.user.name)
        self._notify_country_officers()

    def _create_payslip_run(self, slips):
        """Payroll > Payslip Batches entry for the approved payslips (state Close = done)."""
        self.ensure_one()
        Run = self.env['hr.payslip.run'].sudo().with_context(tracking_disable=True, mail_create_nolog=True)
        run = self.payslip_run_id.sudo()
        if not run:
            run = Run.create({'name': self.name, 'date_start': self.date_from, 'date_end': self.date_to})
            self._system_write({'payslip_run_id': run.id})
        slips.sudo().write({'payslip_run_id': run.id})
        run.write({'state': 'close', 'name': self.name})
        return run

    def _decision_recipients(self):
        """Approved / rejected mails: the payroll's country Officers, then the Payroll
        Managers (Admins included), plus whoever prepared the batch."""
        officers = self.payroll_country_id._country_officers()
        managers = self.env['payroll.country']._payroll_managers()
        return officers, (managers | self.submitted_by) - officers

    def _notify_decision(self, xmlid, kind, label):
        officers, others = self._decision_recipients()
        logs = self.env['payroll.country.notify.log']
        for user in officers | others:
            logs |= self._send_template(xmlid, user, kind)
        if officers or others:
            self._log(body=_("%(what)s notification sent to the %(country)s Payroll Officers (%(officers)s) and the "
                             "Payroll Managers (%(others)s).", what=label, country=self.country_id.name,
                             officers=', '.join(officers.mapped('name')) or '-',
                             others=', '.join(others.mapped('name')) or '-'))
        else:
            self._log(body=_("No Payroll Officer or Manager to notify for %s.") % self.country_id.name)
        return logs

    def _notify_country_officers(self):
        return self._notify_decision('om_hr_payroll_extended_gk.mail_template_payroll_approved_officer',
                                     'approved_officer', _("Approval"))

    def _open_reason_wizard(self, mode):
        self.ensure_one()
        self._check_approver()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.country.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': _("Reject Payroll") if mode == 'reject' else _("Ask for Resubmission"),
            'context': {'default_batch_id': self.id, 'default_mode': mode},
        }

    def action_open_reject_wizard(self):
        return self._open_reason_wizard('reject')

    def action_open_resubmit_wizard(self):
        return self._open_reason_wizard('resubmit')

    def _do_reject(self, reason):
        self.ensure_one()
        self._check_approver()
        if not (reason or '').strip():
            raise UserError(_("A rejection reason is required."))
        self._system_write({'state': 'rejected', 'rejection_reason': reason.strip(),
                            'rejected_by': self.env.uid, 'rejected_date': fields.Datetime.now(),
                            'approved_user_ids': [(5, 0, 0)]})
        self.sudo().line_ids._system_write({'state': 'rejected'})
        self._close_approval_activities(_("Rejected: %s") % reason)
        self._log(body=_("Rejected by %(user)s: %(reason)s", user=self.env.user.name, reason=reason))
        self._notify_decision('om_hr_payroll_extended_gk.mail_template_payroll_rejected', 'rejected',
                              _("Rejection"))
        return True

    def _do_resubmit(self, reason):
        """Sent back to whoever prepared the batch: they check it and submit again."""
        self.ensure_one()
        self._check_approver()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to ask for resubmission."))
        self._system_write({'state': 'resubmit', 'resubmit_reason': reason,
                            'resubmit_by': self.env.uid, 'resubmit_date': fields.Datetime.now(),
                            'approved_user_ids': [(5, 0, 0)]})
        self.sudo().line_ids._system_write({'state': 'calculated'})
        self._close_approval_activities(_("Resubmission requested: %s") % reason)
        self._log(body=Markup(_("<b>Resubmission requested</b> by %(user)s.<br/><b>Reason:</b> %(reason)s"))
                  % {'user': self.env.user.name, 'reason': reason})
        if self.submitted_by:
            self._send_template('om_hr_payroll_extended_gk.mail_template_payroll_resubmit',
                                self.submitted_by, 'resubmit')
        return True

    def action_cancel(self):
        for batch in self:
            batch._check_officer_rights()
            batch._check_editable()
            batch.sudo().line_ids.payslip_id.filtered(lambda s: s.state == 'draft').unlink()
            batch.sudo().line_ids._system_write({'state': 'cancel', 'payslip_id': False})
            batch._system_write({'state': 'cancel'})
            batch._log(body=_("Payroll batch cancelled; its draft payslips were deleted."))
        return True

    # ------------------------------------------------------------ report / send
    def action_generate_report(self):
        self.ensure_one()
        wizard = self.env['payroll.country.report.wizard'].create({
            'batch_id': self.id,
            'payroll_country_id': self.payroll_country_id.id,
            'month': self.month,
            'year': self.year,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.country.report.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _("Generate Payroll Report"),
        }

    def action_send_selected(self):
        """Popup listing every employee of the batch with a Select tick."""
        self.ensure_one()
        return self.env['payroll.country.send.wizard']._open_for(self)

    def action_send_all(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Payslips can be sent only after approval."))
        lines = self.line_ids.filtered(lambda l: l.state == 'approved' and l.email_status not in ('sent', 'queued'))
        if not lines:
            raise UserError(_("Every payslip of this batch is already sent or queued."))
        return lines._send_payslips()

    def action_view_unsent(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('om_hr_payroll_extended_gk.action_payroll_unsent_payslips')
        action['domain'] = [('batch_id', '=', self.id)]
        action['context'] = {'search_default_not_sent': 1}
        return action

    def _log(self, body):
        """Chatter note as the acting user (approvers only have read access)."""
        return self.sudo().message_post(body=body, author_id=self.env.user.partner_id.id,
                                        message_type='comment', subtype_xmlid='mail.mt_note')

    @api.model
    def _notify(self, title, message, kind='info', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': kind, 'sticky': sticky,
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    # ------------------------------------------------------------ mail helpers (templates)
    def _mail_rows(self):
        """Key/value rows for the notification emails. No salary figures (gross / deductions /
        net) in any email: they are seen in the batch and its register only."""
        self.ensure_one()
        return [
            (_("Payroll Reference"), self.name),
            (_("Country"), self.country_id.name),
            (_("Companies"), self.company_names),
            (_("Payroll Month"), tools.month_label(self.month)),
            (_("Payroll Year"), self.year),
            (_("Period"), self.period_label),
            (_("Number of Employees"), str(self.employee_count)),
            (_("Status"), dict(STATES)[self.state]),
            (_("Submitted By"), self.submitted_by.name or ''),
            (_("Approver"), self.approved_by.name or ', '.join(self.approver_user_ids.mapped('name'))),
        ]

    def get_mail_table(self):
        rows = ''.join('<tr><td style="padding:4px 12px 4px 0;color:#555;">%s</td>'
                       '<td style="padding:4px 0;"><strong>%s</strong></td></tr>'
                       % (html_escape(k), html_escape(v or '')) for k, v in self._mail_rows())
        return Markup('<table style="border-collapse:collapse;font-size:14px;">%s</table>' % rows)

    def get_month_label(self):
        return tools.month_label(self.month)
