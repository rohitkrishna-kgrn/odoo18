import hashlib
import json

import babel.dates
import logging
import math
from decimal import ROUND_HALF_UP, Decimal
from collections import defaultdict
from datetime import datetime, time, timedelta

from pytz import UTC, timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_round

from . import tools
from .payroll_logs import SEND_STATUS
from .perf import cached, scoped

_logger = logging.getLogger(__name__)

SYSTEM_CTX = 'payroll_country_system_write'

# Figures a Payroll Officer may type in a draft batch. Each has a `calc_<key>`
# twin holding what the Payroll engine produced; a typed value different from
# it is a manual change (kept across recalculation, audited).
EDITABLE_FIGURES = {
    'lop_days': 'LOP Days',
    'basic': 'Basic Salary',
    'hra': 'HRA',
    'other_allowances': 'Other Allowances',
    'overtime_amount': 'Overtime Pay',
    'other_earnings': 'Other Earnings',
    'epf': 'Employee EPF',
    'esi': 'ESI',
    'other_deductions': 'Other Deductions',
    'lop_amount': 'LOP Deduction',
}
# Everything else in the employee payroll popup can be typed too. Typed values are
# kept (manual_keys) when Fetch / Calculate re-read the source records.
SNAPSHOT_EDITABLE = [
    'employee_name', 'employee_code', 'department_name', 'job_name', 'joining_date', 'employee_status',
    'work_location', 'work_email',
    'contract_ref', 'contract_start', 'contract_end', 'contract_state', 'contract_wage', 'contract_basic',
    'structure_name', 'schedule_name', 'window_from', 'window_to',
    'contract_hra', 'contract_da', 'contract_travel', 'contract_medical', 'contract_other_allowance',
    'contract_pt', 'contract_other_deduction',
    'prev_payslip_ref', 'prev_month', 'prev_year', 'prev_basic', 'prev_gross', 'prev_net', 'prev_state',
    'bank_id', 'bank_name', 'bank_holder', 'bank_account', 'bank_iban', 'bank_branch', 'bank_ifsc', 'bank_route',
    'total_days', 'working_days', 'present_days', 'absent_days', 'half_days', 'late_arrivals',
    'late_deduct_days', 'worked_hours', 'overtime_hours', 'weekly_off_days', 'public_holidays',
    'out_of_contract_days', 'paid_leave_days', 'unpaid_leave_days', 'pending_leave_count', 'leave_detail_ids',
    'pf_esi_entry', 'work_from_home',
]
# typed values of these change the pay -> the payslip is recalculated
# line field -> hr.contract field read by the Payroll salary rules
CONTRACT_COMPONENTS = {
    'contract_wage': 'wage', 'contract_basic': 'basic_salary', 'contract_hra': 'hra', 'contract_da': 'da',
    'contract_travel': 'travel_allowance', 'contract_medical': 'medical_allowance',
    'contract_other_allowance': 'other_allowance', 'contract_pt': 'pt_amount',
    'contract_other_deduction': 'other_deduction',
}
CALC_KEYS = set(CONTRACT_COMPONENTS) | {'pf_esi_entry', 'contract_start', 'contract_end', 'window_from', 'window_to',
             'total_days', 'working_days', 'present_days', 'absent_days', 'paid_leave_days', 'unpaid_leave_days',
             'late_deduct_days', 'work_from_home', 'weekly_off_days', 'public_holidays', 'contract_state', 'structure_name', 'schedule_name'}
# Line value -> (source record, field) it comes from. Typing one of these in the
# popup writes it to the Employee / Contract (never a manual override), and a change
# made on the Employee / Contract refreshes every open payroll line, so the payroll
# and the HR records always show the same value. Everything else on the line comes
# from attendance, leave or history and stays a per-payroll value (manual_keys).
SYNC_FIELDS = {
    'employee_name': ('employee', 'name'),
    'employee_code': ('employee', 'employee_no'),
    'department_name': ('employee', 'department_id'),
    'job_name': ('employee', 'job_title'),
    'joining_date': ('employee', 'doj'),
    'work_location': ('employee', 'work_location_id'),
    'work_email': ('employee', 'work_email'),
    'bank_id': ('employee', 'payroll_bank_id'),
    'bank_name': ('employee', 'payroll_bank_name'),
    'bank_holder': ('employee', 'payroll_bank_holder'),
    'bank_account': ('employee', 'bank_account_no'),
    'bank_iban': ('employee', 'bank_iban_number'),
    'bank_branch': ('employee', 'payroll_bank_branch'),
    'bank_ifsc': ('employee', 'payroll_bank_ifsc'),
    'bank_route': ('employee', 'bank_route_number'),
    'contract_ref': ('contract', 'name'),
    'contract_start': ('contract', 'date_start'),
    'contract_end': ('contract', 'date_end'),
    'contract_state': ('contract', 'state'),
    'structure_name': ('contract', 'struct_id'),
    'schedule_name': ('contract', 'resource_calendar_id'),
    **{lfield: ('contract', cfield) for lfield, cfield in CONTRACT_COMPONENTS.items()},
}
SYNC_REQUIRED = {'employee_name', 'contract_ref', 'contract_start', 'contract_state'}
SYNC_CTX = 'payroll_sync_origin'           # line whose typing is being written to the source
NO_SYNC_CTX = 'payroll_no_line_sync'       # source write that must not refresh payroll lines
BANK_KEYS = {'bank_id', 'bank_name', 'bank_holder', 'bank_account', 'bank_iban', 'bank_branch', 'bank_ifsc', 'bank_route'}
# attendance value -> Payroll worked-days code the salary rules read
WORKED_CODES = {'total_days': 'WORK100', 'present_days': 'PRESENT', 'weekly_off_days': 'SUNDAY',
                'public_holidays': 'PH'}
FREE_FIELDS = {'note', 'send_selected'}
EDITABLE_STATES = ('draft', 'calculated', 'rejected', 'resubmit')

# worked-days / input line fields compared before rewriting a payslip's lines
WORKED_ROW = ('code', 'name', 'sequence', 'number_of_days', 'number_of_hours', 'contract_id')
INPUT_ROW = ('code', 'name', 'contract_id')

OT_CODE = 'PAYROLL_OT'
OTHER_EARN_CODE = 'PAYROLL_OTHER_EARN'
WFH_CODE = 'PAYROLL_WFH'
WFH_DAYS = 30           # fixed 30-day basis, whatever the days in the month
LOP_CODES = ('LOP', 'LATE_LOGIN_DED', 'SICK_HALF_PAY')
DUBAI_TZ = timezone('Asia/Dubai')


class PayrollCountryLine(models.Model):
    _name = 'payroll.country.line'
    _description = 'Country Payroll - Employee Line'
    _inherit = ['payroll.no.mail.chatter', 'mail.thread']     # guard first: it must run before mail.thread
    _order = 'batch_id desc, company_name, employee_name'
    _rec_name = 'employee_name'

    batch_id = fields.Many2one('payroll.country.batch', string='Payroll Batch', required=True,
                               ondelete='cascade', index=True)
    batch_state = fields.Selection(related='batch_id.state', store=True, string='Batch Status')
    payroll_country_id = fields.Many2one(related='batch_id.payroll_country_id', store=True)
    country_id = fields.Many2one(related='batch_id.country_id', store=True, string='Country')
    month = fields.Selection(related='batch_id.month', store=True)
    year = fields.Selection(related='batch_id.year', store=True)
    date_from = fields.Date(related='batch_id.date_from')
    date_to = fields.Date(related='batch_id.date_to')
    period_key = fields.Char(compute='_compute_period_key', store=True, index=True)
    is_live = fields.Boolean(compute='_compute_period_key', store=True, index=True,
                             help="False once the batch is cancelled (the employee can be payrolled again).")
    currency_id = fields.Many2one(related='batch_id.currency_id')

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    contract_id = fields.Many2one('hr.contract', string='Contract')
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True,
                                 help="Paying company = the contract's company.")
    payslip_id = fields.Many2one('hr.payslip', string='Payslip', copy=False, index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('calculated', 'Calculated'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)
    note = fields.Text(string='Remarks')

    # ---- employee snapshot (read in sudo at fetch: officers have no HR access)
    employee_name = fields.Char(string='Employee Name')
    employee_code = fields.Char(string='Employee ID')
    company_name = fields.Char(string='Company Name')
    department_name = fields.Char(string='Department')
    job_name = fields.Char(string='Designation')
    joining_date = fields.Date(string='Joining Date')
    employee_status = fields.Char(string='Employee Status')
    work_location = fields.Char(string='Work Location')
    work_email = fields.Char(string='Employee Email')
    leave_country = fields.Char(string='Leave Location')
    employee_user_id = fields.Many2one('res.users', string='Employee User')

    # ---- contract snapshot
    contract_ref = fields.Char(string='Contract Reference')
    contract_start = fields.Date(string='Contract Start')
    contract_end = fields.Date(string='Contract End')
    contract_state = fields.Char(string='Contract Status')
    contract_wage = fields.Monetary(string='Contract Wage')
    contract_basic = fields.Monetary(string='Contract Basic Salary')
    structure_name = fields.Char(string='Salary Structure')
    schedule_name = fields.Char(string='Working Schedule')
    contract_components = fields.Text(string='Salary Components (old summary)')  # no longer shown
    contract_hra = fields.Monetary(string='House Rent Allowance')
    contract_da = fields.Monetary(string='Special Allowance')
    contract_travel = fields.Monetary(string='Conveyance Allowance')
    contract_medical = fields.Monetary(string='Medical Reimbursement')
    contract_other_allowance = fields.Monetary(string='Other Allowance')
    contract_esi = fields.Monetary(string='ESI (contract)', readonly=True,
                                   help="Not deducted as such. Formula mode: non-zero = ESI applies to this employee.")
    contract_pt = fields.Monetary(string='PT (Professional Tax)')
    contract_other_deduction = fields.Monetary(string='Other Deduction')
    contract_epf = fields.Monetary(string='Employee Provident Fund (contract)', readonly=True,
                                   help="Not deducted as such. Formula mode: non-zero = PF applies to this employee.")
    window_from = fields.Date(string='Payable From')
    window_to = fields.Date(string='Payable To')

    # ---- previous payslip
    prev_payslip_ref = fields.Char(string='Previous Payslip')
    prev_month = fields.Char(string='Previous Payroll Month')
    prev_year = fields.Char(string='Previous Payroll Year')
    prev_basic = fields.Monetary(string='Previous Basic')
    prev_gross = fields.Monetary(string='Previous Gross')
    prev_net = fields.Monetary(string='Previous Net')
    prev_state = fields.Char(string='Previous Payslip Status')

    # ---- attendance
    total_days = fields.Float(string='Days in Period', digits=(16, 2))
    working_days = fields.Float(string='Working Days', digits=(16, 2))
    present_days = fields.Float(string='Present Days', digits=(16, 2))
    absent_days = fields.Float(string='Absent Days', digits=(16, 2),
                               help="Working days not present and not on paid leave. Shown only: absent days are "
                                    "not deducted (LOP = Late Login Days + Unpaid Leave).")
    half_days = fields.Float(string='Half Days', digits=(16, 2))
    late_arrivals = fields.Integer(string='Late Arrivals')
    late_deduct_days = fields.Float(string='Late Login Days', digits=(16, 2),
                                    help="Half a day for every late login past the grace days. Deducted: "
                                         "LOP Days = Late Login Days + Unpaid Leave.")
    worked_hours = fields.Float(string='Worked Hours', digits=(16, 2))
    work_from_home = fields.Boolean(
        string='Work From Home', tracking=True,
        help="India: deducts the Work From Home Deduction (Gross / 30 x 4% x 30) from this month's salary.")
    overtime_hours = fields.Float(string='Overtime Hours', digits=(16, 2))
    weekly_off_days = fields.Float(string='Weekly Off Days', digits=(16, 2))
    public_holidays = fields.Float(string='Public Holidays', digits=(16, 2))
    out_of_contract_days = fields.Float(string='Days Outside Contract', digits=(16, 2),
                                        help="Days of the period before joining / after leaving: unpaid.")

    # ---- leave
    paid_leave_days = fields.Float(string='Paid Leave', digits=(16, 2))
    unpaid_leave_days = fields.Float(string='Unpaid Leave', digits=(16, 2),
                                     help="Approved Unpaid (Loss of Pay type) leave. Deducted: "
                                          "LOP Days = Late Login Days + Unpaid Leave.")
    leave_detail_ids = fields.One2many('payroll.country.line.leave', 'line_id', string='Approved Leave')
    pending_leave_count = fields.Integer(string='Leave Awaiting Approval')

    # ---- salary (final values = what the payslip carries)
    lop_days = fields.Float(string='LOP Days', digits=(16, 2), tracking=True)
    basic = fields.Monetary(string='Basic Salary', tracking=True)
    hra = fields.Monetary(string='HRA', tracking=True)
    other_allowances = fields.Monetary(string='Other Allowances', tracking=True)
    overtime_amount = fields.Monetary(string='Overtime Pay', tracking=True)
    other_earnings = fields.Monetary(string='Other Earnings', tracking=True)
    epf = fields.Monetary(string='Employee EPF', tracking=True,
                          help="India employees only: Salary Administration formula, or a typed amount. Always 0 for everyone else.")
    esi = fields.Monetary(string='ESI', tracking=True,
                          help="India employees only: Salary Administration formula, or a typed amount. Always 0 for everyone else.")
    lop_amount = fields.Monetary(string='LOP Deduction')
    other_deductions = fields.Monetary(string='Other Deductions', tracking=True,
                                       help="Contract / typed other deductions. The Work From Home Deduction is "
                                            "added on top of them (Total Other Deductions).")
    wfh_deduction = fields.Monetary(string='Work From Home Deduction', readonly=True,
                                    help="India, Work From Home ticked: Gross / 30 x 4% x 30. Calculated, never typed.")
    total_other_deductions = fields.Monetary(string='Total Other Deductions', compute='_compute_totals', store=True)
    gross = fields.Monetary(string='Gross Salary', compute='_compute_totals', store=True)
    total_deductions = fields.Monetary(string='Total Deductions', compute='_compute_totals', store=True)
    net = fields.Monetary(string='Net Salary', compute='_compute_totals', store=True)
    pf_india = fields.Boolean(string='India Basic & EPF rules')
    pf_epf_rate = fields.Float(string='EPF %', digits=(16, 2))

    # ---- engine values (before manual changes)
    calc_lop_days = fields.Float(string='Calculated LOP Days', digits=(16, 2))   # LOP before a typed value
    calc_basic = fields.Monetary(string='Calculated Basic')
    calc_hra = fields.Monetary(string='Calculated HRA')
    calc_other_allowances = fields.Monetary(string='Calculated Other Allowances')
    calc_overtime_amount = fields.Monetary(string='Calculated Overtime Pay')
    calc_other_earnings = fields.Monetary(string='Calculated Other Earnings')
    calc_epf = fields.Monetary(string='Calculated EPF')     # formula value (0 in manual mode)
    calc_esi = fields.Monetary(string='Calculated ESI')     # formula value (0 in manual mode)
    pf_wage = fields.Monetary(string='PF Wage', readonly=True,
                              help="min(PF wage % x salary after LOP, PF wage cap) - Salary Administration formula.")
    esi_wage = fields.Monetary(string='ESI Wage', readonly=True,
                               help="Gross earnings after LOP when ESI applies (wage within the ESI limit).")
    pf_employer = fields.Monetary(string='PF Employer Share', readonly=True)
    esi_employer = fields.Monetary(string='ESI Employer Share', readonly=True)
    pf_esi_applies = fields.Boolean(string='PF / ESI Apply', readonly=True,
                                    help="PF and ESI are for India employees only (Leave Location = India). "
                                         "For everyone else EPF / ESI are always 0 and cannot be typed.")
    pf_esi_mode = fields.Selection(related='payroll_country_id.pf_esi_mode', string='Country PF / ESI Default')
    pf_esi_entry = fields.Selection([
        ('formula', 'Formula'),
        ('manual', 'Manual'),
    ], string='PF / ESI', default='formula', required=True, tracking=True,
        help="Formula: EPF / ESI calculated with the Salary Administration formula (read-only). "
             "Manual: EPF / ESI are typed; switching to Manual keeps the current amounts to edit.")
    calc_other_deductions = fields.Monetary(string='Calculated Other Deductions')
    calc_lop_amount = fields.Monetary(string='Calculated LOP Deduction')
    manual_keys = fields.Char(default=',', copy=False,
                              help="Comma list of figures typed by a Payroll Officer.")
    has_manual = fields.Boolean(compute='_compute_has_manual', string='Manually Changed')
    change_log_ids = fields.One2many('payroll.country.change.log', 'line_id', string='Manual Changes')
    calculated_on = fields.Datetime(string='Calculated On', readonly=True)
    source_fingerprint = fields.Char(copy=False)

    # ---- bank (masked copies; full numbers only for payroll staff)
    bank_id = fields.Many2one('res.bank', string='Bank', domain="[('country', '=', country_id)]",
                              help="Banks of the payroll country (Contacts > Configuration > Banks).")
    bank_name = fields.Char(string='Bank Name')
    bank_holder = fields.Char(string='Account Holder')
    bank_account = fields.Char(string='Account Number (full)',
                               groups='om_hr_payroll.group_hr_payroll_user')
    bank_iban = fields.Char(string='IBAN (full)',
                            groups='om_hr_payroll.group_hr_payroll_user')
    bank_account_masked = fields.Char(string='Account Number')
    bank_iban_masked = fields.Char(string='IBAN')
    bank_branch = fields.Char(string='Branch')
    bank_ifsc = fields.Char(string='IFSC')
    bank_route = fields.Char(string='Routing Code')

    # ---- validation
    validation_status = fields.Selection([('ok', 'OK'), ('warning', 'Warning'), ('error', 'Error')],
                                         string='Check', default='ok')
    validation_message = fields.Text(string='Check Details')

    # ---- payslip distribution
    payslip_ref = fields.Char(string='Payslip Reference', compute='_compute_payslip_ref', store=True,
                              help="The payslip's number in Payroll (given at approval), its name before that.")
    email_status = fields.Selection(SEND_STATUS, string='Email Status', tracking=True, index=True)
    email_sent_date = fields.Datetime(string='Email Sent On')
    email_error = fields.Text(string='Email Error')
    send_selected = fields.Boolean(string='Select', help="Tick, then press Send Selected.")
    send_log_ids = fields.One2many('payroll.payslip.send.log', 'line_id', string='Sending History')
    send_count = fields.Integer(compute='_compute_send_count', string='Emails')

    _sql_constraints = [
        ('employee_batch_unique', 'unique(batch_id, employee_id)',
         'An employee can only appear once in a payroll batch.'),
    ]

    def init(self):
        # One live payroll per employee + paying company + period, enforced by Postgres
        # (cancelled batches are not "live", so the period can be re-run).
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS payroll_country_line_live_unique
            ON payroll_country_line (employee_id, company_id, period_key) WHERE is_live
        """)

    # ------------------------------------------------------------ computes
    @api.depends('batch_id.year', 'batch_id.month', 'batch_id.state')
    def _compute_period_key(self):
        for line in self:
            batch = line.batch_id
            line.period_key = '%s-%02d' % (batch.year, int(batch.month)) if batch.year and batch.month else False
            line.is_live = bool(batch) and batch.state != 'cancel'

    @api.depends('basic', 'hra', 'other_allowances', 'overtime_amount', 'other_earnings',
                 'epf', 'esi', 'lop_amount', 'other_deductions', 'wfh_deduction')
    def _compute_totals(self):
        for line in self:
            line.gross = line.basic + line.hra + line.other_allowances + line.overtime_amount + line.other_earnings
            line.total_other_deductions = line.other_deductions + line.wfh_deduction
            line.total_deductions = line.epf + line.esi + line.lop_amount + line.total_other_deductions
            line.net = line.gross - line.total_deductions

    @api.depends('payslip_id.number', 'payslip_id.name')
    def _compute_payslip_ref(self):
        for line in self:
            slip = line.sudo().payslip_id
            line.payslip_ref = slip.number or slip.name or False

    def action_download_payslip(self):
        """Payroll's PaySlip PDF of the selected lines (one PDF for several), like Print >
        PaySlip on a payslip in Payroll."""
        lines = self.filtered('payslip_id')
        if not lines:
            raise UserError(_("Calculate the payroll first: there is no payslip to download yet."))
        user = self.env.user
        for line in lines:
            if not (user._is_payroll_manager() or (user._is_payroll_officer()
                                                and line.country_id in user._payroll_allowed_countries())):
                raise AccessError(_("Only a Payroll Officer of %s can download this payslip.") % line.country_id.name)
        return self.env.ref('om_hr_payroll.action_report_payslip').report_action(lines.sudo().payslip_id)

    # Work From Home Deduction follows the checkbox on screen at once (Save recalculates it)
    @api.onchange('work_from_home')
    def _onchange_work_from_home(self):
        for line in self:
            line.wfh_deduction = line._wfh_amount(line.gross) if line.work_from_home and line.pf_esi_applies else 0.0

    def _wfh_amount(self, gross):
        """Daily Gross = Gross / 30; daily deduction = daily Gross x WFH %; monthly = daily x 30."""
        self.ensure_one()
        rate = self.payroll_country_id.wfh_rate if self.payroll_country_id else 4.0
        daily = (gross or 0.0) / WFH_DAYS
        return float_round(daily * rate / 100.0 * WFH_DAYS, 2)

    @api.depends('manual_keys')
    def _compute_has_manual(self):
        for line in self:
            line.has_manual = bool(line._manual())

    def _compute_send_count(self):
        for line in self:
            line.send_count = len(line.send_log_ids)

    @api.depends('employee_name', 'batch_id.name')
    def _compute_display_name(self):
        for line in self:
            line.display_name = '%s - %s' % (line.employee_name or '', line.batch_id.name or '')

    # ------------------------------------------------------------ live attendance maths
    # Working Days = Present + Absent + Paid Leave + Unpaid Leave. The two onchanges
    # give the same numbers back, so the web client's onchange re-run settles at once.
    @api.onchange('bank_id')
    def _onchange_bank_id(self):
        for line in self:
            if line.bank_id:
                line.bank_name = line.bank_id.name

    # Working Days = Present + Paid Leave + Absent (Absent includes approved unpaid leave).
    # Both onchanges give the same numbers back, so the web client's onchange re-run settles at once.
    @api.onchange('absent_days')
    def _onchange_absent_days(self):
        for line in self:
            line.present_days = max(float_round(line.working_days - line.absent_days - line.paid_leave_days, 2), 0.0)

    @api.onchange('present_days', 'working_days', 'paid_leave_days')
    def _onchange_present_days(self):
        for line in self:
            line.absent_days = max(float_round(line.working_days - line.present_days - line.paid_leave_days, 2), 0.0)

    # LOP Days = Late Login Days + Unpaid Leave (absent days are never deducted)
    @api.onchange('late_deduct_days', 'unpaid_leave_days')
    def _onchange_lop_sources(self):
        for line in self:
            if 'lop_days' not in line._manual():
                line.lop_days = line._policy_lop_days(line.late_deduct_days, line.unpaid_leave_days)

    # LOP Deduction follows LOP Days on screen at once (Save recalculates it through the rules)
    @api.onchange('lop_days')
    def _onchange_lop_days(self):
        for line in self:
            if 'lop_amount' not in line._manual():
                line.lop_amount = line._lop_amount_preview(line.lop_days)

    def _lop_amount_preview(self, lop_days):
        """Loss of Pay rule arithmetic: contract wage / days in period x LOP days."""
        self.ensure_one()
        if not self.total_days:
            return 0.0
        return float_round((self.contract_wage or 0.0) / self.total_days * (lop_days or 0.0), 2)

    def _manual(self):
        return {k for k in (self.manual_keys or '').split(',') if k}

    # ------------------------------------------------------------ write guard
    def _system_write(self, vals):
        return self.with_context(**{SYSTEM_CTX: True}, tracking_disable=True).write(vals)

    @api.model
    def _fmt(self, value):
        if isinstance(value, float):
            return '%.2f' % value
        if isinstance(value, models.BaseModel):
            return ', '.join(value.mapped('display_name'))
        return '' if value in (False, None) else str(value)

    @scoped
    def write(self, vals):
        if self.env.context.get(SYSTEM_CTX):
            return super().write(vals)
        keys = set(vals)
        editable = set(EDITABLE_FIGURES) | set(SNAPSHOT_EDITABLE)
        edited = keys & editable
        refused = {k for k in keys - editable - FREE_FIELDS
                   if not k.startswith(('message_', 'activity_', 'website_message'))}
        if refused:
            raise UserError(_("These payroll values are filled by the system and cannot be edited: %s")
                            % ', '.join(sorted(self._fields[k].string for k in refused if k in self._fields)))
        if 'send_selected' in keys and vals.get('send_selected'):
            for line in self:
                if line.batch_id.state != 'approved':
                    raise UserError(_("Payslips can be selected for sending only after the batch is approved."))
        if edited or 'note' in keys:
            for line in self:
                if line.batch_id.state not in EDITABLE_STATES:
                    raise UserError(_("%s: the batch is %s - payroll values are locked.")
                                    % (line.employee_name, dict(line.batch_id._fields['state']._description_selection(self.env))[line.batch_id.state]))
        if not edited:
            return super().write(vals)
        if keys & {'epf', 'esi', 'pf_esi_entry'}:
            for line in self:
                if not line.pf_esi_applies:
                    raise UserError(_("%s: PF and ESI apply to India employees only.") % line.employee_name)
        if vals.get('work_from_home'):
            for line in self:
                if not line.pf_esi_applies:
                    raise UserError(_("%s: the Work From Home Deduction applies to India employees only.")
                                    % line.employee_name)
        for line in self:
            line._check_officer()
            manual = line._manual()
            line_vals = dict(vals)
            if 'absent_days' in vals and 'present_days' not in vals:
                # absent days are what is left of the working days: typed absences move present days
                working = vals.get('working_days', line.working_days)
                paid = vals.get('paid_leave_days', line.paid_leave_days)
                line_vals['present_days'] = max(float(working or 0) - float(paid or 0)
                                                - float(vals['absent_days'] or 0), 0.0)
            if ('lop_days' in line_vals and 'lop_days' not in manual
                    and {'late_deduct_days', 'unpaid_leave_days'} & set(line_vals)
                    and not float_compare(float(line_vals['lop_days'] or 0),
                                          line._policy_lop_days(line_vals.get('late_deduct_days', line.late_deduct_days),
                                                                line_vals.get('unpaid_leave_days', line.unpaid_leave_days)),
                                          precision_digits=2)):
                # LOP Days filled on screen from Late Login + Unpaid Leave (onchange): not a typed LOP
                line_vals.pop('lop_days')
            if ('lop_amount' in line_vals and 'lop_amount' not in manual
                    and {'lop_days', 'late_deduct_days', 'unpaid_leave_days'} & set(vals)
                    and not float_compare(float(line_vals['lop_amount'] or 0),
                                          line._lop_amount_preview(float(vals.get('lop_days', line.lop_days) or 0)),
                                          precision_digits=2)):
                # LOP Deduction previewed on screen from LOP Days (onchange): the rules recalculate it
                line_vals.pop('lop_amount')
            if vals.get('bank_id') and 'bank_name' not in vals:
                line_vals['bank_name'] = self.env['res.bank'].sudo().browse(vals['bank_id']).name
            entry = line_vals.get('pf_esi_entry') or line.pf_esi_entry
            if ({'epf', 'esi'} & set(vals)) and entry == 'formula':
                entry = line_vals['pf_esi_entry'] = 'manual'      # typing an amount = manual entry
            # employee / contract / bank values: written to the Employee / Contract themselves
            synced = line._push_to_source(line_vals)
            manual -= synced
            logs = []
            for key in sorted(set(line_vals) & editable):
                label = EDITABLE_FIGURES.get(key) or line._fields[key].string
                if key == 'pf_esi_entry':
                    if line_vals[key] != line.pf_esi_entry:
                        if line_vals[key] == 'manual':
                            manual |= {'epf', 'esi'}          # keep the current amounts, now editable
                        else:
                            manual -= {'epf', 'esi'}          # back to the formula
                        sel = dict(line._fields[key]._description_selection(self.env))
                        logs.append({'line_id': line.id, 'field_name': key, 'field_label': label,
                                     'old_value': sel.get(line.pf_esi_entry), 'new_value': sel.get(line_vals[key])})
                    continue
                if key == 'leave_detail_ids':
                    manual.add(key)
                    logs.append({'line_id': line.id, 'field_name': key, 'field_label': label,
                                 'old_value': _('%s line(s)') % len(line.leave_detail_ids),
                                 'new_value': _('edited')})
                    continue
                field = line._fields[key]
                new = line_vals[key]
                if field.type in ('float', 'monetary', 'integer'):
                    new = float(new or 0.0)
                    changed = bool(float_compare(new, line[key] or 0.0, precision_digits=2))
                elif field.type == 'date':
                    new = fields.Date.to_date(new) if new else False
                    changed = new != line[key]
                elif field.type == 'many2one':
                    new = self.env[field.comodel_name].sudo().browse(new or [])
                    changed = new != line.sudo()[key]
                else:
                    new = new or False
                    changed = new != (line.sudo()[key] or False)
                if key in synced:
                    pass                                    # it is the Employee / Contract value now
                elif key in ('epf', 'esi') and entry == 'manual':
                    manual.add(key)
                elif key in EDITABLE_FIGURES:
                    calc = line['calc_' + key]
                    if float_compare(new, calc, precision_digits=2) == 0:
                        manual.discard(key)
                    else:
                        manual.add(key)
                else:
                    manual.add(key)
                if changed:
                    logs.append({'line_id': line.id, 'field_name': key, 'field_label': label,
                                 'old_value': line._fmt(line.sudo()[key]), 'new_value': line._fmt(new),
                                 'calculated_value': line._fmt(line['calc_' + key]) if key in EDITABLE_FIGURES else False,
                                 'synced_to': (_('Employee') if SYNC_FIELDS[key][0] == 'employee' else _('Contract'))
                                 if key in synced else False})
            line_vals['manual_keys'] = ',' + ','.join(sorted(manual)) + ','
            super(PayrollCountryLine, line.sudo().with_context(**{SYSTEM_CTX: True})).write(line_vals)
            if logs:
                self.env['payroll.country.change.log'].sudo().create(logs)
            if synced:
                # re-read the updated Employee / Contract: payable window, bank name... follow
                line.sudo()._refresh_snapshot()
            touched = set(line_vals) & editable
            if touched & BANK_KEYS:
                line.sudo()._refresh_bank_masks()
            if line.payslip_id and touched & (set(EDITABLE_FIGURES) | CALC_KEYS):
                line._calculate()
            elif touched & CALC_KEYS:
                line.sudo()._refresh_lop_preview()
            line.sudo()._validate()
        return True

    def _check_officer(self):
        user = self.env.user
        if self.env.su or user._is_payroll_manager():
            return
        if not user._is_payroll_officer() or self.country_id not in user._payroll_allowed_countries():
            raise AccessError(_("Only a Payroll Officer of %s can change this payroll.") % self.country_id.name)

    # ------------------------------------------------------------ Employee / Contract sync
    def _push_to_source(self, line_vals):
        """Write the typed employee / contract / bank values (SYNC_FIELDS) to the
        Employee and the Contract (sudo: Payroll Officers have no HR access; the
        HR chatter tracking shows who changed what). line_vals gets the value as
        the source now holds it (department as found, contract status label...).
        Returns the synced keys."""
        self.ensure_one()
        keys = set(line_vals) & set(SYNC_FIELDS)
        if not keys:
            return set()
        records = {'employee': self.employee_id.sudo(), 'contract': self.contract_id.sudo()}
        writes = {'employee': {}, 'contract': {}}
        for key in sorted(keys):
            target, fname = SYNC_FIELDS[key]
            record = records[target]
            label = self._fields[key].string
            if not record:
                raise UserError(_("%(employee)s has no contract in this payroll: %(field)s cannot be changed.",
                                  employee=self.employee_name, field=label))
            field = record._fields[fname]
            value = line_vals[key]
            if isinstance(value, str):
                value = value.strip()
            if key in SYNC_REQUIRED and not value:
                raise UserError(_("%s cannot be empty.") % label)
            if key == 'bank_id':
                src = value or False
            elif field.type == 'many2one':
                found = self._find_by_name(field.comodel_name, value, records['employee'].company_id) \
                    if value else self.env[field.comodel_name]
                if value and not found:
                    raise UserError(_('%(field)s: there is no %(model)s named "%(value)s". '
                                      'Type the exact name of an existing one.',
                                      field=label, model=self.env[field.comodel_name]._description, value=value))
                src = found.id
                line_vals[key] = found.name or False
            elif field.type == 'selection':
                options = field._description_selection(self.env)
                match = [k for k, lbl in options if value.lower() in (k.lower(), str(lbl).lower())]
                if not match:
                    raise UserError(_("%(field)s must be one of: %(options)s",
                                      field=label, options=', '.join(str(lbl) for _k, lbl in options)))
                src = match[0]
                line_vals[key] = dict(options)[src]
            elif field.type in ('float', 'monetary', 'integer'):
                src = float(value or 0.0)
            else:
                src = value or False
                line_vals[key] = src
            writes[target][fname] = src
        for target, vals in writes.items():
            if vals:
                records[target].with_context(**{SYNC_CTX: self.id}).write(vals)
        return keys

    @api.model
    def _find_by_name(self, model, name, company):
        """Existing record by exact (case-insensitive) name, the employee's company first."""
        Model = self.env[model].sudo()
        pattern = name.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')
        found = Model.search([('name', '=ilike', pattern)])
        if not found and 'complete_name' in Model._fields and Model._fields['complete_name'].store:
            found = Model.search([('complete_name', '=ilike', pattern)])
        if len(found) > 1 and 'company_id' in Model._fields:
            found = (found.filtered(lambda r: r.company_id == company)
                     or found.filtered(lambda r: not r.company_id) or found)
        return found[:1]

    @api.model
    @scoped
    def _sync_from_source(self, domain, recalc):
        """An Employee / Contract was changed (in HR or from another payroll line):
        every open payroll line built on it re-reads it, and is recalculated when
        the change affects the pay. A failure never blocks the HR save: the line
        is flagged instead."""
        if self.env.context.get(NO_SYNC_CTX):
            return
        origin = self.env.context.get(SYNC_CTX)
        lines = self.sudo().search(domain + [('batch_state', 'in', EDITABLE_STATES), ('id', '!=', origin or 0)])
        for line in lines:
            try:
                with self.env.cr.savepoint():
                    line._refresh_snapshot()
                    if recalc and line.payslip_id:
                        line._calculate()
                    line._validate()
            except UserError as exc:
                _logger.warning("payroll line %s not refreshed after an employee / contract change: %s",
                                line.id, exc)
                line._system_write({'validation_status': 'error', 'validation_message': 'ERROR: %s' % exc})
        return True

    @scoped
    def action_reset_manual(self):
        """Back to the values the Payroll rules calculate."""
        for line in self:
            if line.batch_id.state not in EDITABLE_STATES:
                raise UserError(_("The batch is locked."))
            line._check_officer()
            manual = line._manual()
            if not manual and line.pf_esi_entry == line.payroll_country_id.pf_esi_mode:
                continue
            self.env['payroll.country.change.log'].sudo().create([{
                'line_id': line.id, 'field_name': key,
                'field_label': EDITABLE_FIGURES.get(key) or line._fields[key].string,
                'old_value': line._fmt(line.sudo()[key]) if key != 'leave_detail_ids' else _('edited'),
                'new_value': _('back to calculated / source value')} for key in sorted(manual)])
            line._system_write({'manual_keys': ',', 'pf_esi_entry': line.payroll_country_id.pf_esi_mode,
                                'work_from_home': False})
            line._refresh_snapshot()
            if line.payslip_id:
                line._calculate()
            line.sudo()._validate()
        return True

    # ------------------------------------------------------------ snapshot
    def _payable_window(self, contract, employee, date_from, date_to):
        start = max(contract.date_start or date_from, date_from)
        end = min(contract.date_end or date_to, date_to)
        if employee.departure_date:
            end = min(end, employee.departure_date)
        return start, end

    def _refresh_snapshot(self):
        """Employee, contract, previous payslip, bank, attendance and leave, read
        from the existing models (sudo: Payroll Officers have no HR access)."""
        for line in self.sudo():
            employee = line.employee_id.with_context(active_test=False)
            contract = line.contract_id
            batch = line.batch_id
            start, end = line._payable_window(contract, employee, batch.date_from, batch.date_to)
            status = _('Active') if employee.active else _('Archived')
            if employee.departure_date and employee.departure_date <= batch.date_to:
                status = _('Leaving %s') % employee.departure_date.strftime('%d %b %Y')
            components = []
            for fname in ('basic_salary', 'hra', 'da', 'travel_allowance', 'medical_allowance',
                          'other_allowance', 'esi_amount', 'pt_amount', 'other_deduction'):
                if fname in contract._fields and contract[fname]:
                    components.append('%s: %s' % (contract._fields[fname].string, '{:,.2f}'.format(contract[fname])))
            vals = {
                'employee_name': employee.name,
                'employee_code': employee.employee_no or employee.barcode or str(employee.id),
                'company_name': line.company_id.name,
                'department_name': employee.department_id.name or False,
                'job_name': employee.job_title or employee.job_id.name or False,
                'joining_date': employee.doj or employee.first_contract_date or contract.date_start,
                'employee_status': status,
                'work_location': employee.work_location_id.name or False,
                'work_email': employee.work_email or False,
                'leave_country': dict(employee._fields['country_for_leave']._description_selection(self.env)).get(
                    employee.country_for_leave) if employee.country_for_leave else False,
                'employee_user_id': employee.user_id.id,
                'pf_esi_applies': employee.country_for_leave == 'india',
                'contract_ref': contract.name,
                'contract_start': contract.date_start,
                'contract_end': contract.date_end,
                'contract_state': dict(contract._fields['state']._description_selection(self.env)).get(contract.state),
                'contract_wage': contract.wage,
                'contract_basic': contract.basic_salary,
                'contract_hra': contract.hra,
                'contract_da': contract.da,
                'contract_travel': contract.travel_allowance,
                'contract_medical': contract.medical_allowance,
                'contract_other_allowance': contract.other_allowance,
                'contract_esi': contract.esi_amount,
                'contract_pt': contract.pt_amount,
                'contract_other_deduction': contract.other_deduction,
                'contract_epf': contract.epf_amount,
                'structure_name': contract.struct_id.name or False,
                'schedule_name': contract.resource_calendar_id.name or False,
                'contract_components': '\n'.join(components) or False,
                'window_from': start,
                'window_to': end,
            }
            vals.update(line._previous_payslip_vals())
            vals.update(line._bank_vals())
            vals.update(line._attendance_vals())
            manual = line._manual()
            for key in manual:
                vals.pop(key, None)
            if manual & {'window_from', 'window_to'}:
                start, end = line._effective_window()
                for key, value in (('window_from', start), ('window_to', end)):
                    if key not in manual:
                        vals[key] = value
            line._system_write(vals)
            line._refresh_bank_masks()
            if manual & CALC_KEYS:
                line._refresh_lop_preview()
        return True

    def _effective_window(self):
        """Payable window: contract / employment dates, or the typed payable dates."""
        self.ensure_one()
        batch = self.batch_id
        df, dt = batch.date_from, batch.date_to
        start, end = self._payable_window(self.contract_id.sudo(), self.employee_id.sudo(), df, dt)
        manual = self._manual()
        if 'window_from' in manual and self.window_from:
            start = max(self.window_from, df)
        if 'window_to' in manual and self.window_to:
            end = min(self.window_to, dt)
        return start, end

    def _refresh_bank_masks(self):
        """Masked account / IBAN shown to everyone (bank details are not validated)."""
        for line in self.sudo():
            line._system_write({
                'bank_account_masked': tools.mask(line.bank_account) or False,
                'bank_iban_masked': tools.mask(line.bank_iban) or False,
            })

    def _refresh_lop_preview(self):
        """Absent days / LOP days from the line's (possibly typed) attendance and leave."""
        for line in self.sudo():
            if not line.contract_id:
                continue
            manual = line._manual()
            absent = line.absent_days
            vals = {}
            if 'absent_days' not in manual and manual & {'present_days', 'paid_leave_days', 'working_days'}:
                absent = vals['absent_days'] = max(line.working_days - line.present_days - line.paid_leave_days, 0.0)
            vals['calc_lop_days'] = line._policy_lop_days(line.late_deduct_days, line.unpaid_leave_days)
            if 'lop_days' not in manual:
                vals['lop_days'] = vals['calc_lop_days']
            line._system_write(vals)

    def _line_worked_days(self):
        """Payroll worked days with the line's typed attendance on top (what Compute Sheet reads)."""
        worked, info = self._engine_worked_days()
        manual = self._manual()
        rows = {w['code']: w for w in worked}

        def put(code, value):
            row = rows.get(code)
            if not row:
                row = {'name': code.title(), 'sequence': 50, 'code': code, 'contract_id': self.contract_id.id}
                rows[code] = row
                worked.append(row)
            row['number_of_days'] = float_round(max(value, 0.0), 2)
            row['number_of_hours'] = row['number_of_days'] * 8
        for key, code in WORKED_CODES.items():
            if key in manual:
                put(code, self[key])
        if 'paid_leave_days' in manual:
            sick = sum(rows[c]['number_of_days'] for c in ('SICK_FULL_PAY_DAYS', 'SICK_HALF_PAY_DAYS') if c in rows)
            put('LEAVE', self.paid_leave_days - sick)
        return worked, info

    def _previous_payslip_vals(self):
        slip = self.env['hr.payslip'].sudo().search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '!=', 'cancel'),
            ('date_to', '<', self.batch_id.date_from),
            ('credit_note', '=', False),
        ], order='date_to desc, id desc', limit=1)
        if not slip:
            return {'prev_payslip_ref': False, 'prev_month': False, 'prev_year': False, 'prev_basic': 0.0,
                    'prev_gross': 0.0, 'prev_net': 0.0, 'prev_state': False}
        totals = defaultdict(float)
        cats = defaultdict(float)
        for pl in slip.line_ids:
            totals[pl.code] += pl.total
            cats[pl.category_id.code] += pl.total
        gross = totals.get('GROSS') or (cats['BASIC'] + cats['ALW'])
        return {
            'prev_payslip_ref': slip.number or slip.name,
            'prev_month': slip.date_to.strftime('%B'),
            'prev_year': str(slip.date_to.year),
            'prev_basic': cats['BASIC'],
            'prev_gross': gross,
            'prev_net': totals.get('NET', 0.0),
            'prev_state': dict(slip._fields['state']._description_selection(self.env)).get(slip.state),
        }

    def _bank_data(self):
        """Bank details from the existing employee implementation: core Bank
        Account (res.partner.bank), Bank A/c No (Payroll), IBAN / Route
        (Employee) and the Payroll bank fields of this module."""
        emp = self.employee_id.sudo()
        partner_bank = emp.bank_account_id
        acc = tools.clean(emp.bank_account_no)
        iban = tools.clean(emp.bank_iban_number)
        pb_number = tools.clean(partner_bank.acc_number)
        if pb_number:
            if tools.looks_like_iban(pb_number):
                iban = iban or pb_number
            else:
                acc = acc or pb_number
        if not acc and iban and iban.startswith('AE') and len(iban) == 23:
            acc = iban[-16:]      # UAE IBAN = AE + 2 check + 3 bank + 16 account digits
        bank = emp.payroll_bank_id or partner_bank.bank_id
        return {
            'bank_id': bank.id,
            'bank_name': emp.payroll_bank_name or bank.name or False,
            'holder': emp.payroll_bank_holder or partner_bank.acc_holder_name or False,
            'account': acc,
            'iban': iban,
            'branch': emp.payroll_bank_branch or partner_bank.bank_id.city or False,
            'ifsc': tools.clean(emp.payroll_bank_ifsc) or False,
            'route': emp.bank_route_number or False,
        }

    def _bank_vals(self):
        bank = self._bank_data()
        return {
            'bank_id': bank['bank_id'] or False,
            'bank_name': bank['bank_name'],
            'bank_holder': bank['holder'],
            'bank_account': bank['account'] or False,
            'bank_iban': bank['iban'] or False,
            'bank_account_masked': tools.mask(bank['account']) or False,
            'bank_iban_masked': tools.mask(bank['iban']) or False,
            'bank_branch': bank['branch'],
            'bank_ifsc': bank['ifsc'],
            'bank_route': bank['route'],
        }

    # ------------------------------------------------------------ attendance & leave
    def _engine_worked_days(self):
        """Payroll's own worked-days calculation (om_hr_payroll get_worked_day_lines),
        then the days outside the contract / employment window made unpaid: their
        Sundays and public holidays are removed from the paid lines, so the Loss of
        Pay rule charges them like any other day without attendance."""
        batch = self.batch_id
        contract = self.contract_id.sudo()
        start, end = self._effective_window()
        key = ('engine_worked', self.id, contract.id, contract.date_start, contract.date_end,
               contract.resource_calendar_id.id, batch.date_from, batch.date_to, start, end)
        return cached(key, lambda: self._compute_engine_worked_days(contract, start, end))

    def _compute_engine_worked_days(self, contract, start, end):
        Payslip = self.env['hr.payslip'].sudo()
        batch = self.batch_id
        worked = Payslip.get_worked_day_lines(contract, batch.date_from, batch.date_to)
        outside = set()
        d = batch.date_from
        while d <= batch.date_to:
            if d < start or d > end:
                outside.add(d)
            d += timedelta(days=1)
        info = {'outside': outside, 'start': start, 'end': end}
        if outside:
            sundays_out = len([d for d in outside if d.weekday() == 6])
            ph_dates = {fields.Date.to_date(h.date) for h in self.env['public.holiday'].sudo().search(
                [('date', '>=', batch.date_from), ('date', '<=', batch.date_to)])}
            ph_out = len(outside & ph_dates)
            for wd in worked:
                if wd['code'] == 'SUNDAY' and sundays_out:
                    wd['number_of_days'] = max(wd['number_of_days'] - sundays_out, 0.0)
                    wd['number_of_hours'] = wd['number_of_days'] * 8
                if wd['code'] == 'PH' and ph_out:
                    wd['number_of_days'] = max(wd['number_of_days'] - ph_out, 0.0)
                    wd['number_of_hours'] = wd['number_of_days'] * 8
        return worked, info

    @api.model
    def _policy_lop_days(self, late_login_days, unpaid_leave_days):
        """LOP days = Late Login days + approved Unpaid Leave days, nothing else. Absent days
        (no attendance, no approved leave) are NOT deducted, nor Dubai half-pay sick days, nor
        days before joining / after leaving."""
        return float_round(max(late_login_days or 0.0, 0.0) + max(unpaid_leave_days or 0.0, 0.0), 2)

    @api.model
    def _normalize_worked_for_lop(self, worked):
        """Worked days before the LOP policy is applied: the late-login row is dropped here
        (``_apply_lop_override`` then charges exactly Late Login + Unpaid Leave days), Dubai
        half-pay sick days count as fully paid sick days."""
        rows = []
        for wd in worked:
            if wd['code'] == 'LATE_DEDUCT':
                continue
            if wd['code'] == 'SICK_HALF_PAY_DAYS':
                wd = dict(wd, code='SICK_FULL_PAY_DAYS')
            rows.append(wd)
        return rows

    @api.model
    def _lop_from_worked(self, by_code, dubai):
        """Same arithmetic as the Loss of Pay salary rule / payslip LOP Days."""
        total = by_code.get('WORK100', 0.0)
        accounted = by_code.get('PRESENT', 0.0) + by_code.get('LEAVE', 0.0) \
            + by_code.get('SICK_FULL_PAY_DAYS', 0.0) + by_code.get('SICK_HALF_PAY_DAYS', 0.0) \
            + by_code.get('SUNDAY', 0.0) + by_code.get('PH', 0.0)
        lop = max(total - accounted, 0.0) + by_code.get('LATE_DEDUCT', 0.0)
        if dubai:
            lop += by_code.get('SICK_HALF_PAY_DAYS', 0.0) * 0.5
        return float_round(lop, 2)

    def _leave_requests(self, states):
        user = self.employee_id.sudo().user_id
        if not user:
            return self.env['leave.request']
        batch = self.batch_id
        return self.env['leave.request'].sudo().search([
            ('user_id', '=', user.id),
            ('state', 'in', states),
            ('start_date', '<=', batch.date_to),
            '|', ('end_date', '>=', batch.date_from),
            '&', ('end_date', '=', False), ('start_date', '>=', batch.date_from),
        ], order='start_date')

    def _attendance_vals(self):
        self.ensure_one()
        batch = self.batch_id
        employee = self.employee_id.sudo()
        worked, info = self._engine_worked_days()
        by_code = defaultdict(float)
        for wd in worked:
            by_code[wd['code']] += wd['number_of_days']
        dubai = employee.country_for_leave == 'dubai'
        ph_dates = {fields.Date.to_date(h.date) for h in self.env['public.holiday'].sudo().search(
            [('date', '>=', batch.date_from), ('date', '<=', batch.date_to)])}
        # leave detail, day by day inside the payable window (Sundays / holidays excluded)
        lop_type = self.env.ref('leave_management_rk.leave_type_lop', raise_if_not_found=False)
        details = [(5, 0, 0)]
        unpaid = 0.0
        half_days = 0.0
        approved = self._leave_requests(['approved'])
        for leave in approved:
            first = max(leave.start_date, info['start'])
            last = min(leave.end_date or leave.start_date, info['end'])
            amount = 0.5 if leave.is_half_day else 1.0
            days = 0.0
            d = first
            while d <= last:
                if d.weekday() != 6 and d not in ph_dates:
                    days += amount
                d += timedelta(days=1)
            if leave.leave_type_id.is_permission:
                treatment = 'permission'
                days = 0.0
            elif lop_type and leave.leave_type_id == lop_type:
                treatment = 'unpaid'
                unpaid += days
            elif dubai and leave.leave_type_id.sick_pay_tier:
                treatment = 'sick_dubai'
            else:
                treatment = 'paid'
            if leave.is_half_day and batch.date_from <= leave.start_date <= batch.date_to:
                half_days += 1
            details.append((0, 0, {
                'leave_request_id': leave.id,
                'leave_type': leave.leave_type_id.name,
                'date_from': leave.start_date,
                'date_to': leave.end_date or leave.start_date,
                'is_half_day': leave.is_half_day,
                'days_in_period': days,
                'treatment': treatment,
                'state': dict(leave._fields['state']._description_selection(self.env)).get(leave.state),
            }))
        pending = self._leave_requests(['waiting_manager', 'manager_approved'])
        # attendance register
        Attendance = self.env['hr.attendance'].sudo()
        atts = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', datetime.combine(batch.date_from, time.min)),
            ('check_in', '<=', datetime.combine(batch.date_to, time.max)),
        ])
        late = 0
        for att in atts:
            try:
                if Attendance._is_late_checkin(employee, att.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)):
                    late += 1
            except Exception:  # pragma: no cover - informative figure only
                _logger.exception("late check-in test failed for attendance %s", att.id)
        outside = info['outside']
        sundays_in = len([1 for i in range((batch.date_to - batch.date_from).days + 1)
                          if (batch.date_from + timedelta(days=i)).weekday() == 6
                          and (batch.date_from + timedelta(days=i)) not in outside])
        ph_in = len([d for d in ph_dates if d not in outside])
        total = by_code.get('WORK100', 0.0)
        working = max(total - len(outside) - sundays_in - ph_in, 0.0)
        present = by_code.get('PRESENT', 0.0)
        paid_leave = by_code.get('LEAVE', 0.0) + by_code.get('SICK_FULL_PAY_DAYS', 0.0) \
            + by_code.get('SICK_HALF_PAY_DAYS', 0.0)
        vals = {
            'total_days': total,
            'working_days': working,
            'present_days': present,
            'paid_leave_days': paid_leave,
            'unpaid_leave_days': unpaid,
            'absent_days': max(working - present - paid_leave, 0.0),     # unpaid leave included
            'half_days': half_days,
            'late_arrivals': late,
            'late_deduct_days': by_code.get('LATE_DEDUCT', 0.0),
            'worked_hours': sum(atts.mapped('worked_hours')),
            'overtime_hours': sum(atts.mapped('overtime_hours')) if 'overtime_hours' in atts._fields else 0.0,
            'weekly_off_days': by_code.get('SUNDAY', 0.0),
            'public_holidays': by_code.get('PH', 0.0),
            'out_of_contract_days': float(len(outside)),
            'leave_detail_ids': details,
            'pending_leave_count': len(pending),
        }
        vals['calc_lop_days'] = self._policy_lop_days(vals['late_deduct_days'], vals['unpaid_leave_days'])
        if 'lop_days' not in self._manual():
            vals['lop_days'] = vals['calc_lop_days']
        return vals

    def _fingerprint(self, worked=None):
        """What the calculation was based on: worked days, approved leave, contract figures."""
        self.ensure_one()
        if worked is None:
            worked, _info = self._engine_worked_days()
        contract = self.contract_id.sudo()
        payload = {
            'worked': sorted((w['code'], round(w['number_of_days'], 2)) for w in worked),
            'leave': sorted((l.id, l.state, str(l.start_date), str(l.end_date), l.is_half_day)
                            for l in self._leave_requests(['approved'])),
            'contract': [contract.id, contract.state, str(contract.date_start), str(contract.date_end),
                         contract.wage, contract.basic_salary, contract.struct_id.id]
                        + [contract[f] for f in ('hra', 'da', 'travel_allowance', 'medical_allowance',
                                                 'other_allowance', 'esi_amount', 'pt_amount', 'other_deduction')
                           if f in contract._fields],
        }
        return hashlib.sha1(json.dumps(payload, default=str).encode()).hexdigest()

    # ------------------------------------------------------------ calculation
    def _calculate(self):
        """Run the existing Payroll engine for each line: Payroll worked days
        (+ contract window, + typed LOP days) -> payslip -> Compute Sheet (the
        configured salary rules), then the typed figures on top, Gross / Net
        re-added the way the NET rule does. The line shows what the payslip holds."""
        for line in self:
            line_s = line.sudo()
            contract = line_s.contract_id
            if not contract or not contract.struct_id:
                line._system_write({'state': 'draft'})
                continue
            if line_s.payslip_id and line_s.payslip_id.state != 'draft':
                raise UserError(_("%s: payslip %s is no longer a draft in Payroll; it cannot be recalculated.")
                                % (line.employee_name, line_s.payslip_id.number or line_s.payslip_id.name))
            worked, _info = line_s._line_worked_days()
            worked = line_s._normalize_worked_for_lop(worked)
            by_code = defaultdict(float)
            for wd in worked:
                by_code[wd['code']] += wd['number_of_days']
            dubai = line_s.employee_id.country_for_leave == 'dubai'
            rule_lop = line_s._lop_from_worked(by_code, dubai)
            manual = line._manual()
            # LOP policy: the Loss of Pay rule must charge exactly Late Login + Unpaid Leave days
            # (or the typed LOP Days); the worked days it reads are shifted to match
            calc_lop = line_s._policy_lop_days(line_s.late_deduct_days, line_s.unpaid_leave_days)
            target = line.lop_days if 'lop_days' in manual else calc_lop
            line_s._apply_lop_override(worked, target - rule_lop)
            # contract salary components typed on the line are already on the contract
            # (SYNC_FIELDS): the salary rules read them from there
            slip = line_s._ensure_payslip(worked)
            slip.compute_sheet()
            engine = line_s._slip_amounts(slip)
            line_s._apply_overrides(slip, manual)
            pf_esi = line_s._pf_esi_formula(line_s._slip_amounts(slip))
            if not line_s.pf_esi_applies:           # PF / ESI: India employees only
                epf = esi = 0.0
            elif line.pf_esi_entry == 'manual':
                epf = line.epf if 'epf' in manual else 0.0
                esi = line.esi if 'esi' in manual else 0.0
            else:
                epf, esi = pf_esi['epf'], pf_esi['esi']
            line_s._apply_pf_esi(slip, epf, esi, manual)
            final = line_s._slip_amounts(slip)
            vals = {
                'calc_lop_days': calc_lop,
                'calc_basic': engine['basic'],
                'calc_hra': engine['hra'],
                'calc_other_allowances': engine['other_allowances'],
                'calc_overtime_amount': 0.0,
                'calc_other_earnings': 0.0,
                'calc_epf': pf_esi['epf'],
                'calc_esi': pf_esi['esi'],
                'pf_wage': pf_esi['pf_wage'],
                'esi_wage': pf_esi['esi_wage'],
                'pf_employer': pf_esi['pf_employer'],
                'esi_employer': pf_esi['esi_employer'],
                'calc_other_deductions': engine['other_deductions'],
                'calc_lop_amount': engine['lop_amount'],
                'lop_days': slip.lop_days,
                'basic': final['basic'],
                'hra': final['hra'],
                'other_allowances': final['other_allowances'],
                'overtime_amount': final['overtime_amount'],
                'other_earnings': final['other_earnings'],
                'epf': final['epf'],
                'esi': final['esi'],
                'lop_amount': final['lop_amount'],
                'other_deductions': final['other_deductions'],
                'wfh_deduction': final['wfh_deduction'],
                'pf_india': slip.pf_india,
                'pf_epf_rate': slip.pf_epf_rate,
                'calculated_on': fields.Datetime.now(),
                'source_fingerprint': line_s._fingerprint(),
            }
            if line.batch_id.state in ('draft', 'calculated'):
                vals['state'] = 'calculated'
            line._system_write(vals)
            if float_compare(line.net, final['net'], precision_digits=2):
                _logger.warning("payroll line %s net %s != payslip net %s", line.id, line.net, final['net'])
        return True

    def _apply_lop_override(self, worked, delta):
        """Typed LOP days: shift the Present (and Late Login) days the Loss of Pay
        rule reads, so LOP, India Basic/EPF and Net all follow the typed value."""
        rows = {w['code']: w for w in worked}
        contract_id = self.contract_id.id

        def row(code, name, seq):
            if code not in rows:
                rows[code] = {'name': name, 'sequence': seq, 'code': code, 'number_of_days': 0.0,
                              'number_of_hours': 0.0, 'contract_id': contract_id}
                worked.append(rows[code])
            return rows[code]

        present = row('PRESENT', 'Present (Attendance)', 30)
        late = row('LATE_DEDUCT', 'Late Login Deduction', 35)
        if delta > 0:       # more LOP: fewer present days, then extra deduction days
            take = min(delta, present['number_of_days'])
            present['number_of_days'] -= take
            late['number_of_days'] += delta - take
        elif delta < 0:     # less LOP: drop deduction days first, then add present days
            give = -delta
            take = min(give, late['number_of_days'])
            late['number_of_days'] -= take
            present['number_of_days'] += give - take
        for r in (present, late):
            r['number_of_days'] = float_round(max(r['number_of_days'], 0.0), 2)
            r['number_of_hours'] = r['number_of_days'] * 8

    def _ensure_payslip(self, worked):
        """Create / refresh this line's draft payslip exactly like Payroll's
        Generate Payslips (onchange_employee_id with the contract). The draft payslip
        is machine-written on every calculation: no chatter tracking on it (the batch
        keeps the audit trail), which also makes Fetch / Save much faster."""
        quiet = dict(tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
        Payslip = self.env['hr.payslip'].sudo().with_context(**quiet)
        batch = self.batch_id
        inputs = Payslip.get_inputs(self.contract_id, batch.date_from, batch.date_to)
        vals = {
            'employee_id': self.employee_id.id,
            'date_from': batch.date_from,
            'date_to': batch.date_to,
            'name': self._payslip_name(),
            'contract_id': self.contract_id.id,
            'struct_id': self.contract_id.struct_id.id,
            'company_id': self.company_id.id,
            'country_line_id': self.id,
            'worked_days_line_ids': [(5, 0, 0)] + [(0, 0, w) for w in worked],
            'input_line_ids': [(5, 0, 0)] + [(0, 0, i) for i in inputs],
        }
        slip = self.payslip_id.with_context(**quiet)
        if slip:
            # rewrite only what changed: replacing the worked-days / input lines deletes and
            # recreates them on every calculation, which was most of the Save / Fetch time
            if self._slip_rows(slip.worked_days_line_ids, WORKED_ROW) == self._slip_rows(worked, WORKED_ROW):
                vals.pop('worked_days_line_ids')
            if self._slip_rows(slip.input_line_ids, INPUT_ROW) == self._slip_rows(inputs, INPUT_ROW):
                vals.pop('input_line_ids')
            for key in [k for k in vals if k not in ('worked_days_line_ids', 'input_line_ids')]:
                current = slip[key]
                current = current.id if isinstance(current, models.BaseModel) else current
                if current == vals[key]:
                    vals.pop(key)
            if vals:
                slip.write(vals)
        else:
            slip = Payslip.create(vals)
            self._system_write({'payslip_id': slip.id})
        return slip

    @api.model
    def _slip_rows(self, rows, keys):
        """Comparable form of worked-days / input lines (records or value dicts)."""
        def val(row, key):
            v = row.get(key) if isinstance(row, dict) else row[key]
            if isinstance(v, models.BaseModel):
                v = v.id
            if isinstance(v, float):
                v = round(v, 4)
            return v or False
        return sorted(tuple(val(row, k) for k in keys) for row in rows)

    def _payslip_name(self):
        """Payroll's own payslip name (om_hr_payroll onchange_employee_id): the month the
        26th -> 25th period ends in."""
        locale = self.env.context.get('lang') or 'en_US'
        month = babel.dates.format_date(date=datetime.combine(self.batch_id.date_to, time.min),
                                        format='MMMM-y', locale=locale)
        return _('Salary Slip of %s for %s') % (self.employee_id.name, month)

    @api.model
    def _slip_amounts(self, slip):
        totals = defaultdict(float)
        cats = defaultdict(float)
        for pl in slip.line_ids:
            totals[pl.code] += pl.total
            cats[pl.category_id.code] += pl.total
        basic = cats['BASIC']
        alw = cats['ALW']
        hra = totals['HRA']
        ot = totals[OT_CODE]
        oe = totals[OTHER_EARN_CODE]
        ded = abs(cats['DED'])
        epf = abs(totals['EPF'])
        esi = abs(totals['ESI'])
        lop = abs(sum(totals[c] for c in LOP_CODES))
        wfh = abs(totals[WFH_CODE])
        return {
            'basic': basic,
            'hra': hra,
            'other_allowances': alw - hra - ot - oe,
            'overtime_amount': ot,
            'other_earnings': oe,
            'gross': basic + alw,
            'epf': epf,
            'esi': esi,
            'lop_amount': lop,
            'other_deductions': ded - epf - esi - lop - wfh,
            'wfh_deduction': wfh,
            'net': totals['NET'],
        }

    def _rule(self, slip, code):
        rules = slip.struct_id._get_parent_structure().rule_ids if slip.struct_id else self.env['hr.salary.rule']
        rule = rules.filtered(lambda r: r.code == code)[:1]
        if not rule:
            rule = self.env['hr.salary.rule'].sudo().search([('code', '=', code)], limit=1)
        return rule

    def _set_slip_line(self, slip, code, amount):
        lines = slip.line_ids.filtered(lambda l: l.code == code)
        if lines:
            lines[0].write({'amount': amount, 'quantity': 1.0, 'rate': 100.0})
            lines[1:].unlink()
            return
        if not float_round(amount, 2):
            return
        rule = self._rule(slip, code)
        if not rule:
            raise UserError(_("Salary rule %s is missing in Payroll - cannot apply the manual value.") % code)
        self.env['hr.payslip.line'].sudo().create({
            'slip_id': slip.id,
            'salary_rule_id': rule.id,
            'contract_id': slip.contract_id.id,
            'employee_id': slip.employee_id.id,
            'name': rule.name,
            'code': rule.code,
            'category_id': rule.category_id.id,
            'sequence': rule.sequence,
            'appears_on_payslip': rule.appears_on_payslip,
            'condition_select': 'none',
            'amount_select': 'fix',
            'amount_fix': amount,
            'amount': amount,
            'quantity': 1.0,
            'rate': 100.0,
        })

    def _apply_overrides(self, slip, manual):
        """Typed figures on the payslip lines (as when a payroll user edits a
        Salary Computation line), then Gross / Net re-added like the NET rule."""
        def alw_others(exclude):
            return [l for l in slip.line_ids if l.category_id.code == 'ALW' and l.code not in exclude]

        if 'basic' in manual:
            self._set_slip_line(slip, 'BASIC', self.basic)
        if 'hra' in manual:
            self._set_slip_line(slip, 'HRA', self.hra)
        if 'other_allowances' in manual:
            others = alw_others(('HRA', 'ALLOWANCE', OT_CODE, OTHER_EARN_CODE))
            fixed = sum(l.total for l in others)
            if self.other_allowances >= fixed:
                self._set_slip_line(slip, 'ALLOWANCE', self.other_allowances - fixed)
            else:
                for l in others:
                    l.write({'amount': 0.0})
                self._set_slip_line(slip, 'ALLOWANCE', self.other_allowances)
        self._set_slip_line(slip, OT_CODE, self.overtime_amount if 'overtime_amount' in manual else 0.0)
        self._set_slip_line(slip, OTHER_EARN_CODE, self.other_earnings if 'other_earnings' in manual else 0.0)
        # PF and ESI never come from the salary rules: cleared here, then set by
        # _apply_pf_esi (Salary Administration formula or the typed amount).
        self._set_slip_line(slip, 'EPF', 0.0)
        self._set_slip_line(slip, 'ESI', 0.0)
        if 'lop_amount' in manual:
            others = [l for l in slip.line_ids if l.code in LOP_CODES and l.code != 'LOP']
            fixed = abs(sum(l.total for l in others))
            if self.lop_amount >= fixed:
                self._set_slip_line(slip, 'LOP', -(self.lop_amount - fixed))
            else:
                for l in others:
                    l.write({'amount': 0.0})
                self._set_slip_line(slip, 'LOP', -self.lop_amount)
        if 'other_deductions' in manual:
            others = [l for l in slip.line_ids if l.category_id.code == 'DED'
                      and l.code not in ('EPF', 'ESI', 'DEDUCTION', WFH_CODE) + LOP_CODES]
            fixed = abs(sum(l.total for l in others))
            if self.other_deductions >= fixed:
                self._set_slip_line(slip, 'DEDUCTION', -(self.other_deductions - fixed))
            else:
                for l in others:
                    l.write({'amount': 0.0})
                self._set_slip_line(slip, 'DEDUCTION', -self.other_deductions)
        # Work From Home Deduction (India): its own payslip line, on the final Gross; one line,
        # updated on every calculation, removed (0) when unticked; other deductions untouched
        slip.invalidate_recordset(['line_ids'])
        gross = sum(l.total for l in slip.line_ids if l.category_id.code in ('BASIC', 'ALW'))
        wfh = self._wfh_amount(gross) if self.work_from_home and self.pf_esi_applies else 0.0
        self._set_slip_line(slip, WFH_CODE, -wfh)
        self._readd_totals(slip)

    def _readd_totals(self, slip):
        slip.invalidate_recordset(['line_ids'])
        cats = defaultdict(float)
        for pl in slip.line_ids:
            cats[pl.category_id.code] += pl.total
        gross = cats['BASIC'] + cats['ALW']
        self._set_slip_line(slip, 'GROSS', gross)
        self._set_slip_line(slip, 'NET', gross - abs(cats['DED']))

    @api.model
    def _round_rupee(self, value, method='round'):
        """Excel-like rounding to the unit (salary_processing_gk round_amount)."""
        value = float(value or 0.0)
        if method == 'up':
            return float(math.ceil(value - 1e-9))
        return float(Decimal(repr(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    def _pf_esi_formula(self, amounts):
        """PF / ESI of the removed Salary Administration module (salary_processing_gk
        calc_engine, Section J), on this line's figures:
        - PF applies when the contract carries an EPF amount; PF wage = min(70% of the
          salary after LOP, 25,000); employee PF = 12% of it (rounded), employer 12%.
        - ESI applies when the contract carries an ESI amount and the wage is <= 21,000;
          ESI wage = gross earnings after LOP; employee 0.75%, employer 3.25% (rounded up).
        Rates come from the Payroll Country. Computed for India employees only (shown as
        the calculated value); applied only when the line's PF / ESI is Formula."""
        self.ensure_one()
        cfg = self.payroll_country_id
        zero = dict(epf=0.0, esi=0.0, pf_wage=0.0, esi_wage=0.0, pf_employer=0.0, esi_employer=0.0)
        if not self.pf_esi_applies:                 # India employees only
            return zero
        wage = self.contract_wage or 0.0
        earned = max(wage - amounts['lop_amount'], 0.0)
        res = dict(zero)
        if self.contract_epf:
            pf_wage = self._round_rupee(earned * cfg.pf_wage_ratio / 100.0)
            if cfg.pf_wage_cap:
                pf_wage = min(pf_wage, cfg.pf_wage_cap)
            res.update(pf_wage=pf_wage,
                       epf=self._round_rupee(pf_wage * cfg.pf_employee_rate / 100.0),
                       pf_employer=self._round_rupee(pf_wage * cfg.pf_employer_rate / 100.0))
        if self.contract_esi and (not cfg.esi_wage_threshold or wage <= cfg.esi_wage_threshold):
            esi_wage = earned + amounts['overtime_amount'] + amounts['other_earnings']
            res.update(esi_wage=esi_wage,
                       esi=self._round_rupee(esi_wage * cfg.esi_employee_rate / 100.0, 'up'),
                       esi_employer=self._round_rupee(esi_wage * cfg.esi_employer_rate / 100.0, 'up'))
        return res

    def _apply_pf_esi(self, slip, epf, esi, manual):
        self._set_slip_line(slip, 'EPF', -epf)
        self._set_slip_line(slip, 'ESI', -esi)
        if slip.pf_india:
            slip.write({'pf_basic': self.basic if 'basic' in manual else slip.pf_basic,
                        'pf_epf_amount': epf})
        self._readd_totals(slip)

    # ------------------------------------------------------------ validation
    def _validation_issues(self, deep=False):
        """(errors, warnings) for one line. deep=True also re-reads attendance,
        leave and contract to detect changes since the calculation."""
        self.ensure_one()
        line = self.sudo()
        errors, warnings = [], []
        employee = line.employee_id.with_context(active_test=False)
        contract = line.contract_id
        config = line.payroll_country_id
        if not contract:
            errors.append(_("No contract"))
        elif not contract.struct_id:
            errors.append(_("Contract %s has no Salary Structure") % contract.name)
        elif contract.state not in ('open', 'close'):
            errors.append(_("Contract %s is not running") % contract.name)
        if not employee.user_id:
            errors.append(_("Employee has no linked user: attendance and leave cannot be read"))
        elif config.leave_location and employee.country_for_leave != config.leave_location:
            errors.append(_("Leave location is %(loc)s, not %(country)s: the %(country)s salary rules would not apply",
                            loc=line.leave_country or _('not set'), country=config.country_id.name))
        if line.state == 'draft' or not line.payslip_id:
            errors.append(_("Not calculated"))
        elif line.payslip_id.state not in ('draft', 'done'):
            errors.append(_("Payslip %s was cancelled in Payroll") % line.payslip_ref)
        elif float_compare(line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET')[:1].total or 0.0,
                           line.net, precision_digits=2):
            errors.append(_("Payslip %s was changed in Payroll after the calculation - Recalculate")
                          % line.payslip_ref)
        dupes = self.env['hr.payslip'].sudo().search([
            ('employee_id', '=', employee.id),
            ('id', '!=', line.payslip_id.id),
            ('state', '!=', 'cancel'),
            ('credit_note', '=', False),
        ] + line.batch_id._same_month_payslip_domain())
        if dupes:
            errors.append(_("Payroll already has payslip(s) for this month: %s")
                          % ', '.join(dupes.mapped(lambda s: '%s (%s)' % (s.number or s.name, s.state))))
        if deep and line.payslip_id and line.source_fingerprint and line.state != 'draft' \
                and line._fingerprint() != line.source_fingerprint:
            errors.append(_("Attendance, leave or contract changed after the calculation - Recalculate"))
        if line.pending_leave_count:
            warnings.append(_("%s leave request(s) still awaiting approval (not counted)") % line.pending_leave_count)
        if line.state != 'draft' and line.net <= 0:
            warnings.append(_("Net salary is zero or negative"))
        if not line.work_email:
            warnings.append(_("No work email: the payslip cannot be emailed"))
        if line._manual():
            warnings.append(_("Manually changed: %s") % ', '.join(
                EDITABLE_FIGURES.get(k) or line._fields[k].string for k in sorted(line._manual())))
        return errors, warnings

    def _validate(self, deep=False):
        for line in self:
            errors, warnings = line._validation_issues(deep=deep)
            line._system_write({
                'validation_status': 'error' if errors else ('warning' if warnings else 'ok'),
                'validation_message': '\n'.join(['ERROR: %s' % e for e in errors]
                                                + ['Warning: %s' % w for w in warnings]) or False,
            })
        return True

    def action_open_line(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.country.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('om_hr_payroll_extended_gk.view_payroll_country_line_form').id, 'form')],
            'target': 'new',
            'name': self.employee_name,
        }

    @scoped
    def action_recalculate_line(self):
        for line in self:
            if line.batch_id.state not in EDITABLE_STATES:
                raise UserError(_("The batch is locked."))
            line._check_officer()
            line._refresh_snapshot()
            line._calculate()
            line._validate()
        return True

    # ------------------------------------------------------------ payslip emails
    def action_send_payslips(self):
        """Send the approved payslips of exactly these lines (list selection)."""
        if not self:
            raise UserError(_("Select at least one employee, or use Send All on the batch. Nothing was sent."))
        return self._send_payslips()

    def action_resend_payslip(self):
        """Explicit resend of an already sent / failed payslip."""
        return self._send_payslips(allow_resend=True)

    def action_mark_resend(self):
        self._check_send_rights()
        self._system_write({'email_status': 'resend'})
        return True

    def _check_send_rights(self):
        user = self.env.user
        for line in self:
            if line.batch_id.state != 'approved':
                raise UserError(_("%s: payslips can be sent only from an approved payroll batch.")
                                % line.employee_name)
            if not (user._is_payroll_manager() or (user._is_payroll_officer()
                                                and line.country_id in user._payroll_allowed_countries())):
                raise AccessError(_("Only a Payroll Officer of %s can send these payslips.") % line.country_id.name)

    def get_my_payslips_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        action = self.env.ref('om_hr_payroll_extended_gk.action_my_payslips')
        return '%s/odoo/action-%s' % (base, action.id)

    def _send_payslips(self, allow_resend=False):
        self._check_send_rights()
        template = self.env.ref('om_hr_payroll_extended_gk.mail_template_payslip_employee')
        report = self.env.ref('om_hr_payroll.action_report_payslip')
        Log = self.env['payroll.payslip.send.log'].sudo()
        done = skipped = 0
        for line in self:
            line_s = line.sudo()
            if line.email_status in ('sent', 'queued') and not allow_resend:
                skipped += 1
                continue
            slip = line_s.payslip_id
            attempt = len(line_s.send_log_ids) + 1
            base = {'line_id': line.id, 'payslip_ref': line.payslip_ref, 'attempt': attempt}
            if not slip or slip.state != 'done':
                Log.create(dict(base, status='failed', failure_reason=_("Approved payslip not found")))
                line._system_write({'email_status': 'failed', 'email_error': _("Approved payslip not found"),
                                    'send_selected': False})
                continue
            email = (line_s.employee_id.work_email or '').strip()
            if not email:
                Log.create(dict(base, status='no_email', failure_reason=_("Employee has no work email")))
                line._system_write({'email_status': 'no_email', 'work_email': False,
                                    'email_error': _("Employee has no work email"), 'send_selected': False})
                continue
            try:
                with self.env.cr.savepoint():
                    # the payslip PDF is attached to this email only (no salary figure in the
                    # body); every other payroll email has no attachment
                    pdf, _fmt = self.env['ir.actions.report'].sudo()._render_qweb_pdf(report.report_name, [slip.id])
                    attachment = self.env['ir.attachment'].sudo().create({
                        'name': 'Payslip_%s.pdf' % (slip.number or slip.name).replace('/', '_'),
                        'raw': pdf,
                        'res_model': 'hr.payslip',
                        'res_id': slip.id,
                        'mimetype': 'application/pdf',
                    })
                    mail_id = template.sudo().send_mail(line.id, force_send=False, email_values={
                        'email_to': email,
                        'recipient_ids': [],
                        'attachment_ids': [(4, attachment.id)],
                        'auto_delete': False,
                        'model': False,             # not posted in the chatter
                        'res_id': False,
                    })
                    mail = self.env['mail.mail'].sudo().browse(mail_id)
                    log = Log.create(dict(base, status='queued', email_to=email, mail_id=mail.id,
                                          mail_message_id=mail.mail_message_id.id))
                    mail.write({'payroll_send_log_id': log.id})
                    line._system_write({'email_status': 'queued', 'work_email': email, 'email_error': False,
                                        'send_selected': False})
                    done += 1
            except Exception as exc:  # recorded, never silently dropped
                _logger.exception("payslip email for line %s failed", line.id)
                Log.create(dict(base, status='failed', email_to=email, failure_reason=str(exc)))
                line._system_write({'email_status': 'failed', 'email_error': str(exc), 'send_selected': False})
        message = _("%(done)s payslip email(s) queued.", done=done)
        if skipped:
            message += ' ' + _("%s already sent or queued were skipped (use Resend on the line).") % skipped
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Send Payslips"), 'message': message, 'sticky': False,
                       'type': 'success' if done else 'warning',
                       'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}},
        }

    def _sync_mail_state(self, mail):
        """Line + history follow the real mail.mail state (queued / sent / failed)."""
        log = mail.payroll_send_log_id.sudo()
        if not log:
            return
        state = mail.state
        if state == 'sent':
            status, reason = 'sent', False
        elif state in ('exception', 'cancel'):
            status, reason = 'failed', mail.failure_reason or (_("Cancelled") if state == 'cancel' else _("Delivery failed"))
        else:
            status, reason = 'queued', False
        vals = {'status': status, 'failure_reason': reason}
        if status == 'sent':
            vals['sent_date'] = fields.Datetime.now()
        log.write(vals)
        line = log.line_id
        latest = line.send_log_ids.sorted('id', reverse=True)[:1]
        if latest == log:
            lvals = {'email_status': status, 'email_error': reason}
            if status == 'sent':
                lvals['email_sent_date'] = vals['sent_date']
            line._system_write(lvals)
