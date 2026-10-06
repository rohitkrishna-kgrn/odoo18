from datetime import date

from odoo import models, fields, api
from odoo.exceptions import UserError

from odoo.addons.leave_management_rk.models.leave_period import (
    leave_month_anchor,
    leave_month_bounds,
)


class HrLeaveBalanceWizard(models.TransientModel):
    _name = 'hr.leave.balance.wizard'
    _description = 'HR Leave Balance Management'

    user_id = fields.Many2one('res.users', string='Employee', required=True)
    employee_doj = fields.Date(
        string='DOJ', compute='_compute_employee_doj',
        help="Date of joining, taken from Employees > Settings > DOJ.")
    employee_country = fields.Selection(
        related='user_id.country', string='Country', readonly=True)
    balance_year = fields.Selection(
        selection='_get_year_selection', string='Year', required=True,
        default=lambda self: str(fields.Date.today().year),
        help="Only the current calendar year can be picked here.")
    leave_month_label = fields.Char(
        string='Leave Period',
        compute='_compute_leave_month_label',
        help="The employee's full leave year: 26 Dec of the previous year "
             "to 25 Dec of the selected Year. The balances below are always "
             "the leave month currently in progress within that year, for "
             "both India and Dubai (UAE) - see _leave_year_bounds."
    )
    line_ids = fields.One2many('hr.leave.balance.wizard.line', 'wizard_id', string='Leave Balances')

    @api.model
    def _get_year_selection(self):
        """Only the current calendar year is selectable here."""
        current_year = str(fields.Date.today().year)
        return [(current_year, current_year)]

    def _leave_year_bounds(self):
        """(start, end) of the selected Year's leave period: 26 Dec of the
        previous year to 25 Dec of the selected year - e.g. Year 2026 ->
        (2025-12-26, 2026-12-25). This spans the 12 leave-months named
        January through December of that year (see leave_period.py). Same
        window for India and Dubai (UAE) - only how each country's leave
        types behave month to month within it differs."""
        self.ensure_one()
        year = int(self.balance_year or fields.Date.today().year)
        start, _unused_end = leave_month_bounds(date(year, 1, 1))
        _unused_start, end = leave_month_bounds(date(year, 12, 1))
        return start, end

    @api.depends('balance_year')
    def _compute_leave_month_label(self):
        for rec in self:
            if not rec.balance_year:
                rec.leave_month_label = ''
                continue
            start, end = rec._leave_year_bounds()
            rec.leave_month_label = '%s (%s - %s)' % (
                rec.balance_year, start.strftime('%d %b %Y'), end.strftime('%d %b %Y'))

    def _leave_period_balance(self, leave_type, start, end):
        """(entitlement, taken, remaining) for one leave type over the
        employee's whole leave period [start, end] - computed fresh from
        approved leave.request history every time, not read from a stored
        leave.balance row, so it can never go stale or show 0 just because a
        monthly cron hasn't run yet for the period currently in progress."""
        self.ensure_one()
        field = 'hours_requested' if leave_type.is_permission else 'days_requested'
        requests = self.env['leave.request'].search([
            ('user_id', '=', self.user_id.id),
            ('leave_type_id', '=', leave_type.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', start),
            ('start_date', '<=', end),
        ])
        taken = sum(requests.mapped(field))
        entitlement = leave_type.annual_entitlement
        return entitlement, taken, entitlement - taken

    @api.depends('user_id')
    def _compute_employee_doj(self):
        # `doj` is defined in om_hr_payroll (which depends on this module), so
        # guard for it not being installed; sudo as the wizard is open to non-HR.
        Employee = self.env['hr.employee'].sudo()
        has_doj = 'doj' in Employee._fields
        for wiz in self:
            employee = wiz.user_id.employee_ids[:1].sudo() if wiz.user_id else Employee
            wiz.employee_doj = employee.doj if (has_doj and employee) else False

    @api.onchange('user_id', 'balance_year')
    def _onchange_user_id(self):
        # Always clear first: the block below rebuilds line_ids from
        # scratch, and this guarantees no leave type can ever appear twice
        # or carry a stale balance from a previously-selected employee.
        self.line_ids = [(5, 0, 0)]
        if not self.user_id:
            return

        LeaveBalance = self.env['leave.balance']
        LeaveType = self.env['leave.type']
        # Permission (3 hrs, reset every leave month) is listed like any other
        # type, so HR can see every employee's hours for the month in progress.
        domain = [
            '|', ('country_scope', '=', False), ('country_scope', '=', self.user_id.country),
            ('active', '=', True),
        ]
        leave_types = LeaveType.search(domain, order='name')

        lines = []
        current_anchor = leave_month_anchor(fields.Date.today())
        for lt in leave_types:
            # The stored leave.balance row for the leave month currently in
            # progress is the single source of truth - it's exactly what
            # action_save writes to and what the Leave Request form's
            # Available Balance reads, so a manual correction made here and
            # saved must keep showing here too, not be silently recomputed
            # away next time the wizard opens. Same for India and Dubai
            # (UAE) - only the fallback below (used when no row exists yet)
            # differs by what each leave type is configured with.
            balance_rec = LeaveBalance.search([
                ('user_id', '=', self.user_id.id),
                ('leave_type_id', '=', lt.id),
                ('date', '=', current_anchor),
            ], limit=1)
            if balance_rec:
                balance_value = balance_rec.balance
            elif lt.restart_accrual_after_leave:
                # No row yet, and this type only builds up from zero after the
                # employee's own most recent completed leave of this type (see
                # the field's help) - project the same figure the cron itself
                # will write once it runs, rather than a generic
                # Entitlement-minus-Taken guess that doesn't apply here. 0.0
                # if they have no completed leave of this type yet at all -
                # HR fills this in by hand until their first cycle begins.
                balance_value = LeaveBalance._restart_accrual_projected_balance(self.user_id, lt)
            elif lt.accrual_mode == 'accrue' and lt.annual_entitlement:
                # Dubai Annual Leave: monthly days x leave months elapsed since DOJ (January if none)
                # (capped at the entitlement) less approved leave this leave
                # year - the figure the cron/backfill itself lands on.
                start, end = self._leave_year_bounds()
                months = current_anchor.month
                if LeaveBalance._uses_doj_cycle(self.user_id, lt):
                    # Dubai Annual Leave accrues from the employee's DOJ and
                    # is reset to zero on every DOJ anniversary.
                    window = LeaveBalance._doj_cycle_window(self.user_id, current_anchor)
                    start, end = window or (start, end)
                    months = LeaveBalance._doj_cycle_months_elapsed(self.user_id, current_anchor)
                _entitlement, taken, _remaining = self._leave_period_balance(lt, start, end)
                accrued = lt.monthly_accrual_days * months
                if lt.cap_at_entitlement:
                    accrued = min(accrued, lt.annual_entitlement)
                balance_value = accrued - taken
            elif lt.is_permission:
                # No row yet: the monthly cron will reset it to this anyway.
                balance_value = lt.monthly_reset_value
            elif lt.annual_entitlement:
                # No row yet for this period at all (e.g. a brand new
                # employee, or the monthly cron hasn't seeded it yet) - fall
                # back to a live Entitlement-minus-Taken figure over the
                # whole leave year instead of showing a misleading 0.
                start, end = self._leave_year_bounds()
                _entitlement, _taken, remaining = self._leave_period_balance(lt, start, end)
                balance_value = remaining
            else:
                # No Annual Entitlement configured either (Loss of Pay,
                # Compensation Leave) - nothing sensible to fall back to.
                balance_value = 0.0
            lines.append((0, 0, {'leave_type_id': lt.id, 'balance': balance_value}))
        self.line_ids = lines

    def action_save(self):
        if not self.user_id:
            raise UserError("Please select an employee.")

        # A saved figure always corrects the leave month currently in
        # progress, the one the approval flow and monthly cron actually
        # read/write - same for India and Dubai (UAE).
        write_anchor = leave_month_anchor(fields.Date.today())
        LeaveBalance = self.env['leave.balance']

        for line in self.line_ids:
            if not line.leave_type_id:
                continue
            line_balance = line.balance
            balance_rec = LeaveBalance.search([
                ('user_id', '=', self.user_id.id),
                ('leave_type_id', '=', line.leave_type_id.id),
                ('date', '=', write_anchor),
            ], limit=1)
            if balance_rec:
                balance_rec.balance = line_balance
            else:
                LeaveBalance.create({
                    'user_id': self.user_id.id,
                    'leave_type_id': line.leave_type_id.id,
                    'date': write_anchor,
                    'balance': line_balance,
                })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved',
                'message': f'Leave balances updated for {self.user_id.name}.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_reset_all_leaves(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only System Administrators can reset leave balances.")
        self.env['leave.balance'].action_manual_reset_leaves()
        # The popup stays open after the reset, so its lines still hold the
        # figures loaded before it - and a following Save Changes would write
        # them straight back over the fresh ones. Rebuild them from the reset
        # balances and reopen this same wizard record.
        self.env.flush_all()
        self.invalidate_recordset()
        self._onchange_user_id()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leave Reset Complete',
                'message': 'All leave balances have been reset to defaults.',
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': self._name,
                    'res_id': self.id,
                    'view_mode': 'form',
                    'views': [(False, 'form')],
                    'target': 'new',
                },
            },
        }


class HrLeaveBalanceWizardLine(models.TransientModel):
    _name = 'hr.leave.balance.wizard.line'
    _description = 'Leave Balance Wizard Line'

    wizard_id = fields.Many2one('hr.leave.balance.wizard', string='Wizard')
    leave_type_id = fields.Many2one('leave.type', string='Leave Type')
    is_permission = fields.Boolean(related='leave_type_id.is_permission', readonly=True)
    leave_type_label = fields.Char(string='Leave Type', compute='_compute_leave_type_label')
    balance = fields.Float(string='Remaining Balance')
    taken_this_year = fields.Float(
        string='Taken This Year', compute='_compute_taken_this_year', readonly=True,
        help="Approved requests for this leave type within the employee's current "
             "leave year (26 Dec - 25 Dec), computed live - always reflects reality "
             "even between cron runs. Remaining Balance is not simply Annual "
             "Entitlement minus this figure: most types (Casual Leave, Dubai's "
             "Annual Leave) accrue progressively month by month rather than "
             "granting the full year upfront, so Remaining Balance - the stored, "
             "authoritative figure the cron/approvals actually maintain - is the "
             "one to trust for 'can this request be approved', not a year-end math.")
    balance_label = fields.Char(string='Unit', compute='_compute_balance_label')

    @api.depends('leave_type_id')
    def _compute_leave_type_label(self):
        for rec in self:
            rec.leave_type_label = rec.leave_type_id.name or ''

    @api.depends('leave_type_id', 'wizard_id.user_id', 'wizard_id.balance_year')
    def _compute_taken_this_year(self):
        for rec in self:
            if not (rec.leave_type_id and rec.wizard_id.user_id):
                rec.taken_this_year = 0.0
                continue
            start, end = rec.wizard_id._leave_year_bounds()
            LeaveBalance = self.env['leave.balance']
            if LeaveBalance._uses_doj_cycle(rec.wizard_id.user_id, rec.leave_type_id):
                start, end = LeaveBalance._doj_cycle_window(
                    rec.wizard_id.user_id, leave_month_anchor(fields.Date.today())) or (start, end)
            if rec.leave_type_id.is_permission:
                # Resets monthly, so show only this leave month's hours.
                start, end = leave_month_bounds(leave_month_anchor(fields.Date.today()))
            _entitlement, taken, _remaining = rec.wizard_id._leave_period_balance(
                rec.leave_type_id, start, end)
            rec.taken_this_year = taken

    @api.depends('is_permission', 'leave_type_id.balance_unit_period', 'leave_type_id.dubai_annual_pool',
                 'wizard_id.employee_country')
    def _compute_balance_label(self):
        for rec in self:
            if rec.is_permission:
                rec.balance_label = 'hrs'
                continue
            dubai_pool_active = (
                rec.leave_type_id.dubai_annual_pool and rec.wizard_id.employee_country == 'dubai'
            )
            period = 'year' if dubai_pool_active else rec.leave_type_id.balance_unit_period
            rec.balance_label = 'days/month' if period == 'month' else 'days/year'
