from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

from .leave_period import (
    leave_month_anchor,
    leave_month_bounds,
    leave_month_label as format_leave_month,
    shift_leave_month,
)

ACTIVE_REQUEST_STATES = ('waiting_manager', 'manager_approved', 'approved')
COUNTRY_LABELS = {'india': 'India', 'dubai': 'Dubai (UAE)'}

# UAE sick-leave pay rule (client requirement 2026-09-26): of an employee's
# cumulative APPROVED Sick Leave for a calendar year, the first
# SICK_FULL_PAY_LIMIT days are Full Pay (no extra deduction — approved paid
# leave is already fully paid via the normal payroll worked-days mechanism),
# the next (SICK_MAX_PAY_CONSIDERED - SICK_FULL_PAY_LIMIT) are Half Pay (see
# Payroll's "Sick Leave Half Pay Deduction" salary rule), and days beyond
# SICK_MAX_PAY_CONSIDERED are outside this calculation entirely (no half-pay
# deduction is applied to them — they stay fully paid like any other approved
# leave unless HR separately marks that request unpaid).
SICK_FULL_PAY_LIMIT = 15
SICK_MAX_PAY_CONSIDERED = 45


class LeaveRequest(models.Model):
    _name = 'leave.request'
    _description = 'Leave Request'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, required=True)
    employee_country = fields.Selection(
        related='user_id.country', store=True, string='Country',
        help="India/Dubai category of the employee this request belongs to — "
             "drives which leave types are selectable.")
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    is_half_day = fields.Boolean(string='Half Day')
    start_date = fields.Date(string='Start Date / Date', required=True)
    end_date = fields.Date(string='End Date')
    days_requested = fields.Float(string='Days Requested', compute='_compute_days_requested', store=True)
    hours_requested = fields.Float(string='Hours Requested')
    reason = fields.Text(string='Reason')
    applied_date = fields.Datetime(string='Applied Date', readonly=True)
    dha_certificate = fields.Binary(string='Upload DHA Sick Leave Certificate')
    dha_certificate_filename = fields.Char(string='DHA Certificate Filename')
    is_dubai_sick_leave = fields.Boolean(
        compute='_compute_is_dubai_sick_leave', store=False
    )
    manager_remarks = fields.Text(string='Manager Remarks')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_manager', 'Waiting Manager Approval'),
        ('manager_approved', 'Manager Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='draft', string='Status', tracking=True)
    paid = fields.Boolean(string='Paid Leave')
    balance_deducted = fields.Boolean(string='Balance Deducted', default=False)
    available_balance = fields.Float(
        string="Available Balance (Days / Hrs)",
        compute='_compute_available_balance',
        store=False
    )
    is_permission_type = fields.Boolean(
        string='Is Permission',
        compute='_compute_is_permission_type',
        store=False
    )
    leave_month_label = fields.Char(
        string='Leave Month',
        compute='_compute_leave_month_label',
        store=False,
        help="The 26th-to-25th leave month(s) this request's dates fall in. "
             "Shows both when the request straddles the 26th."
    )

    @api.depends('employee_country', 'leave_type_id', 'days_requested')
    def _compute_is_dubai_sick_leave(self):
        for rec in self:
            rec.is_dubai_sick_leave = (
                rec.employee_country == 'dubai'
                and bool(rec.leave_type_id)
                and rec.leave_type_id.requires_dha_certificate
                and rec.days_requested >= 2
            )

    @api.depends('leave_type_id')
    def _compute_is_permission_type(self):
        for rec in self:
            rec.is_permission_type = bool(rec.leave_type_id and rec.leave_type_id.is_permission)

    def _balance_anchor(self):
        """The leave.balance row (by date) this request draws its balance
        from and is refunded to on reject/cancel - the single source of
        truth shared by _compute_available_balance, action_request's
        sufficiency check, and the approval wizard's deduction/restore.

        Dubai carries one running balance for the whole leave year, so it
        always uses the leave month currently in progress, regardless of
        this request's own start_date. India uses the leave month named
        after this request's own start_date, as before.
        """
        self.ensure_one()
        today = fields.Date.today()
        if self.employee_country == 'dubai' and not (
                self.leave_type_id and self.leave_type_id.is_permission):
            # Permission resets monthly for everyone, so like India it is
            # charged to the request's own leave month.
            return leave_month_anchor(today)
        return leave_month_anchor(self.start_date or today)

    def _projected_raw_balance(self, current_balance):
        """``current_balance`` carried forward to this request's own leave
        month, for a Dubai accruing type (Annual Leave).

        Dubai draws on one running balance (the leave month in progress, see
        _balance_anchor), but a request starting in a LATER leave month can
        use what will have accrued by then: +Monthly Accrual per month, capped
        at the entitlement, and a fresh start from zero when January opens
        (reset_at_year_end) - the same steps the monthly cron will take, so
        the figure shown is what will actually be there. Start dates in the
        current or an earlier month, and every other type, are unchanged.
        """
        self.ensure_one()
        lt = self.leave_type_id
        if not (self.start_date and self.employee_country == 'dubai'
                and lt.accrual_mode == 'accrue' and not lt.is_permission):
            return current_balance
        anchor = leave_month_anchor(fields.Date.today())
        target = leave_month_anchor(self.start_date)
        balance = current_balance
        while anchor < target:
            anchor = shift_leave_month(anchor, 1)
            if anchor.month == 1 and lt.reset_at_year_end:
                balance = lt.initial_balance
            balance += lt.monthly_accrual_days
            if lt.cap_at_entitlement and lt.annual_entitlement:
                balance = min(balance, lt.annual_entitlement)
        return balance

    @api.depends('user_id', 'employee_country', 'leave_type_id', 'start_date', 'end_date',
                 'days_requested', 'hours_requested', 'state', 'balance_deducted')
    def _compute_available_balance(self):
        """Always reads leave.balance fresh (store=False, no caching) so a
        balance corrected via the Employee Leave Balance wizard is reflected
        the next time this computes - immediately on the same request if the
        user_id/leave_type_id/start_date it depends on change, or on the next
        time a new leave request form is opened.

        Shows the NET balance after this request - the underlying
        leave.balance row minus what this request asks for (days, or hours
        for a permission type) - so the figure already reads 30 - 2 = 28
        while the request is still moving through the approval pipeline,
        not just after the approval wizard actually deducts it. Once
        balance_deducted is true the leave.balance row itself already holds
        the post-deduction figure (see LeaveApprovalWizard.action_approve),
        so it's shown as-is rather than subtracted a second time. Rejected
        and cancelled requests never had (or kept) a deduction, so they show
        the raw balance too.

        See _balance_anchor for which leave month/year this resolves to per
        country - the same anchor the wizard's save, the submission-time
        sufficiency check, and the approval wizard's deduction/restore all
        use, so this figure is never out of step with what actually gets
        enforced or corrected elsewhere.
        """
        LeaveBalance = self.env['leave.balance']
        for rec in self:
            rec.available_balance = 0.0
            if not rec.user_id or not rec.leave_type_id:
                continue
            first_of_month = rec._balance_anchor()
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('date', '=', first_of_month),
            ], limit=1)
            raw_balance = balance_record.balance if balance_record else 0.0
            if not balance_record and rec.leave_type_id.is_permission:
                raw_balance = LeaveBalance._get_permission_balance(
                    rec.user_id, rec.leave_type_id, first_of_month)
            if rec.balance_deducted or rec.state in ('rejected', 'cancelled'):
                rec.available_balance = raw_balance
            else:
                requested = rec.hours_requested if rec.leave_type_id.is_permission else rec.days_requested
                rec.available_balance = rec._projected_raw_balance(raw_balance) - requested

    @api.depends('start_date', 'end_date')
    def _compute_leave_month_label(self):
        """Which 26th-to-25th leave month(s) [start_date, end_date] falls in.

        A request entirely inside one period (e.g. 23-25 Jun, both inside the
        26 May-25 Jun "June" period) shows just that period. A request that
        crosses the 26th (e.g. 23-28 Jun, spilling into the 26 Jun-25 Jul
        "July" period) shows every period it touches, oldest first.

        Purely informational - which balance this request is actually
        charged against is a separate, country-specific decision made by
        _balance_anchor (India: the period of start_date; Dubai: whichever
        period is current), unaffected by this display.
        """
        for rec in self:
            rec.leave_month_label = ''
            if not rec.start_date:
                continue
            end = rec.end_date or rec.start_date
            start_anchor = leave_month_anchor(rec.start_date)
            end_anchor = leave_month_anchor(end)
            if end_anchor <= start_anchor:
                rec.leave_month_label = format_leave_month(start_anchor)
                continue
            labels = []
            anchor = start_anchor
            while anchor <= end_anchor:
                labels.append(format_leave_month(anchor))
                anchor = shift_leave_month(anchor, 1)
            rec.leave_month_label = ', '.join(labels)

    @api.depends('start_date', 'end_date', 'is_half_day', 'leave_type_id')
    def _compute_days_requested(self):
        for rec in self:
            if rec.leave_type_id and rec.leave_type_id.is_permission:
                rec.days_requested = 0.0
            elif rec.is_half_day:
                rec.days_requested = 0.5
            elif rec.start_date and rec.end_date:
                rec.days_requested = float((rec.end_date - rec.start_date).days + 1)
            else:
                rec.days_requested = 0.0

    @api.onchange('is_half_day', 'start_date')
    def _onchange_half_day(self):
        if self.is_half_day and self.start_date:
            self.end_date = self.start_date

    @api.onchange('leave_type_id')
    def _onchange_leave_type(self):
        if self.leave_type_id and not self.leave_type_id.is_permission:
            self.hours_requested = 0.0
        if self.leave_type_id and not self.leave_type_id.allows_half_day:
            self.is_half_day = False
        if self.leave_type_id and self.leave_type_id.is_permission:
            self.is_half_day = False

    def _get_employee_manager_user(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.user_id.id)], limit=1
        )
        if employee and employee.parent_id and employee.parent_id.user_id:
            return employee.parent_id.user_id
        return False

    def action_request(self):
        for rec in self:
            if not rec.leave_type_id:
                raise UserError("Please select a Leave Type.")

            if rec.leave_type_id.country_scope and rec.leave_type_id.country_scope != rec.user_id.country:
                raise UserError(
                    f"{rec.leave_type_id.name} is only applicable to "
                    f"{COUNTRY_LABELS.get(rec.leave_type_id.country_scope, rec.leave_type_id.country_scope)} employees."
                )

            if not rec.reason or not rec.reason.strip():
                raise UserError("Please provide a Reason before submitting this leave request.")

            same_date_duplicate = self.search([
                ('id', '!=', rec.id),
                ('user_id', '=', rec.user_id.id),
                ('start_date', '=', rec.start_date),
                ('end_date', '=', rec.end_date),
                ('state', 'in', ACTIVE_REQUEST_STATES),
            ], limit=1)
            if same_date_duplicate:
                date_display = str(rec.start_date)
                if rec.end_date and rec.end_date != rec.start_date:
                    date_display += f" to {rec.end_date}"
                raise UserError(
                    "A leave request has already been submitted for that date.\n\n"
                    f"Leave Date: {date_display}\n"
                    f"Existing Leave Type: {same_date_duplicate.leave_type_id.name}"
                )

            LeaveBalance = self.env['leave.balance']

            # See _balance_anchor: Dubai checks the leave month currently in
            # progress (one running balance all year); India checks the
            # request's own leave month.
            balance_anchor = rec._balance_anchor()
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('date', '=', balance_anchor)
            ], limit=1)
            current_balance = balance_record.balance if balance_record else 0
            if not balance_record and rec.leave_type_id.is_permission:
                current_balance = LeaveBalance._get_permission_balance(
                    rec.user_id, rec.leave_type_id, balance_anchor)

            # Multiple requests of the same leave type can share a leave
            # month now, but they all draw on the same leave.balance row.
            # Other requests still pending (not yet deducted - that only
            # happens at HR approval) have already claimed part of it, so
            # subtract their share before checking this one against what's
            # actually left, otherwise two pending requests could each pass
            # the check against the same undiminished balance.
            other_pending = rec.search([
                ('id', '!=', rec.id),
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('state', 'in', ACTIVE_REQUEST_STATES),
                ('balance_deducted', '=', False),
            ])
            already_committed = sum(
                (r.hours_requested if r.leave_type_id.is_permission else r.days_requested)
                for r in other_pending
                if r._balance_anchor() == balance_anchor
            )
            available_balance = rec._projected_raw_balance(current_balance) - already_committed

            if rec.leave_type_id.is_permission:
                if not rec.hours_requested or rec.hours_requested <= 0:
                    raise UserError("Please specify hours requested for permission leave.")
                if rec.hours_requested > available_balance:
                    raise UserError(
                        f"Insufficient permission hours. Available: {available_balance} hrs, "
                        f"Requested: {rec.hours_requested} hrs"
                    )
            else:
                if not rec.end_date:
                    raise UserError("Please specify an end date.")
                if rec.is_half_day and not rec.leave_type_id.allows_half_day:
                    raise UserError(f"Half day is not applicable for {rec.leave_type_id.name}.")
                if rec.days_requested > available_balance:
                    raise UserError(
                        f"Insufficient leave balance for {rec.leave_type_id.name}. "
                        f"Available: {available_balance}, Requested: {rec.days_requested}"
                    )

            if rec.is_dubai_sick_leave and not rec.dha_certificate:
                raise UserError(
                    "A DHA Sick Leave Certificate is mandatory for Dubai employees "
                    "requesting Sick Leave of 2 or more days."
                )

            manager_user = rec._get_employee_manager_user()
            if manager_user:
                rec.write({'state': 'waiting_manager', 'applied_date': fields.Datetime.now()})
                rec._send_mail_to_manager(manager_user)
            else:
                # No manager configured — skip to manager_approved, notify HR
                rec.write({'state': 'manager_approved', 'applied_date': fields.Datetime.now()})
                rec._send_mail_to_hr()

    def action_manager_approve(self):
        for rec in self:
            if rec.state != 'waiting_manager':
                raise UserError("Only leaves waiting for manager approval can be approved here.")
            manager_user = rec._get_employee_manager_user()
            if manager_user and self.env.user != manager_user:
                raise UserError("Only the direct manager of this employee can approve this request.")
            rec.write({'state': 'manager_approved'})
            rec._send_mail_to_hr()

    def action_manager_reject_wizard(self):
        self.ensure_one()
        manager_user = self._get_employee_manager_user()
        if manager_user and self.env.user != manager_user:
            raise UserError("Only the direct manager of this employee can reject this request.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject with Remarks',
            'res_model': 'leave.manager.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id},
        }

    def action_hr_reject_wizard(self):
        self.ensure_one()
        if self.state != 'manager_approved':
            raise UserError("Only manager-approved leave requests can be rejected here.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject with Remarks',
            'res_model': 'leave.manager.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id},
        }

    def action_open_approve_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Approve Leave',
            'res_model': 'leave.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id}
        }

    def action_reject(self):
        for rec in self:
            if rec.state not in ('waiting_manager', 'manager_approved'):
                raise UserError(
                    "Only requests waiting for approval can be rejected. "
                    "Use Cancel Leave to reverse a leave that is already approved."
                )
            rec.write({'balance_deducted': False, 'state': 'rejected'})

    def _restore_balance(self, rec):
        LeaveBalance = self.env['leave.balance']
        first_of_month = rec._balance_anchor()
        balance_record = LeaveBalance.search([
            ('user_id', '=', rec.user_id.id),
            ('leave_type_id', '=', rec.leave_type_id.id),
            ('date', '=', first_of_month)
        ], limit=1)
        if balance_record:
            if rec.leave_type_id.is_permission:
                balance_record.balance += rec.hours_requested
            else:
                balance_record.balance += rec.days_requested

    def action_open_cancel_wizard(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError("Only approved leave requests can be cancelled.")
        if not self.env.user.has_group('leave_management_rk.group_hr_manager'):
            raise UserError("Only HR can cancel an already-approved leave.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cancel Leave',
            'res_model': 'leave.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id},
        }

    def action_cancel_approved(self):
        """Reverse an already-approved leave and restore its deducted balance.

        Distinct from Reject: Reject only applies before HR approval and never
        touches the balance (nothing was deducted yet); Cancel is the only path
        that can move a leave out of 'approved', and it always refunds whatever
        was deducted, keeping "rejected" (never granted) and "cancelled"
        (granted, then reversed) unambiguous in reporting.
        """
        if not self.env.user.has_group('leave_management_rk.group_hr_manager'):
            raise UserError("Only HR can cancel an already-approved leave.")
        for rec in self:
            if rec.state != 'approved':
                raise UserError("Only approved leave requests can be cancelled.")
            if rec.balance_deducted:
                self._restore_balance(rec)
            rec.write({'balance_deducted': False, 'state': 'cancelled'})

    def _send_mail_to_manager(self, manager_user):
        if not manager_user.email:
            return
        leave_type = self.leave_type_id.name
        duration = (f"{self.hours_requested} hrs" if self.leave_type_id.is_permission
                    else ("Half Day (0.5)" if self.is_half_day else f"{self.days_requested} day(s)"))
        date_info = str(self.start_date)
        if self.end_date and self.end_date != self.start_date:
            date_info += f" to {self.end_date}"
        body_html = f"""
            <p>Dear {manager_user.name},</p>
            <p><strong>{self.user_id.name}</strong> has submitted a leave request requiring your approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Leave Type</b></td><td style="padding:4px 10px;">{leave_type}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Date</b></td><td style="padding:4px 10px;">{date_info}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Duration</b></td><td style="padding:4px 10px;">{duration}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Reason</b></td><td style="padding:4px 10px;">{self.reason or '-'}</td></tr>
            </table>
            <p>Please log in and go to <b>Leave → Team Approval</b> to approve or reject.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Leave Approval Needed — {self.user_id.name} ({leave_type})",
            'body_html': body_html,
            'email_to': manager_user.email,
            'auto_delete': True,
        }).send()

    def _send_mail_to_hr(self):
        hr_group = self.env.ref('leave_management_rk.group_hr_manager', raise_if_not_found=False)
        if not hr_group:
            return
        hr_emails = [u.email for u in hr_group.users if u.email]
        if not hr_emails:
            return
        leave_type = self.leave_type_id.name
        duration = (f"{self.hours_requested} hrs" if self.leave_type_id.is_permission
                    else ("Half Day (0.5)" if self.is_half_day else f"{self.days_requested} day(s)"))
        date_info = str(self.start_date)
        if self.end_date and self.end_date != self.start_date:
            date_info += f" to {self.end_date}"
        body_html = f"""
            <p>Dear HR,</p>
            <p>The leave request from <strong>{self.user_id.name}</strong> has been approved by the department manager and requires your final approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Leave Type</b></td><td style="padding:4px 10px;">{leave_type}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Date</b></td><td style="padding:4px 10px;">{date_info}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Duration</b></td><td style="padding:4px 10px;">{duration}</td></tr>
            </table>
            <p>Please go to <b>Leave → Team Approval</b> to proceed.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Leave Ready for HR Approval — {self.user_id.name}",
            'body_html': body_html,
            'email_to': ','.join(hr_emails),
            'auto_delete': True,
        }).send()

    def _sick_leave_units(self):
        """[(date, weight)] this request contributes, oldest first.

        A half-day request is a single 0.5-weighted unit; anything else is
        one 1.0-weighted unit per calendar day from start_date to end_date —
        the same granularity days_requested already uses, just exploded to
        one entry per day so a multi-day request can straddle a pay-tier
        boundary partway through (see get_dubai_sick_pay_split).
        """
        self.ensure_one()
        if self.is_half_day:
            return [(self.start_date, 0.5)]
        if not self.start_date or not self.end_date:
            return []
        units = []
        day = self.start_date
        while day <= self.end_date:
            units.append((day, 1.0))
            day += timedelta(days=1)
        return units

    @api.model
    def get_dubai_sick_pay_split(self, user, period_start, period_end):
        """Full Pay / Half Pay day counts, within [period_start, period_end],
        for `user`'s approved Sick Leave — used by Payroll to compute the
        Sick Leave Half Pay deduction on a Dubai employee's payslip.

        Walks every approved Sick Leave day for the calendar year
        `period_start` falls in, oldest first, tracking a running total: the
        first SICK_FULL_PAY_LIMIT days of the year are Full Pay, the next
        (SICK_MAX_PAY_CONSIDERED - SICK_FULL_PAY_LIMIT) are Half Pay, and
        anything past SICK_MAX_PAY_CONSIDERED is outside this calculation.
        Only days that also fall inside [period_start, period_end] (this
        payslip's own period) are counted into the returned totals, so a
        single request that crosses a payslip boundary or a pay-tier
        boundary is split correctly either way.

        Only meaningful for Dubai employees — callers should confirm the
        employee's country first (Sick Leave's monthly reset-to-1 balance
        still applies unchanged for India, see leave.type's dubai_annual_pool).
        """
        result = {'full_pay_days': 0.0, 'half_pay_days': 0.0}
        sick_type = self.env.ref('leave_management_rk.leave_type_sick', raise_if_not_found=False)
        if not sick_type or not user or not period_start or not period_end:
            return result

        year_start = period_start.replace(month=1, day=1)
        year_end = period_start.replace(month=12, day=31)
        requests = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', sick_type.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', year_start),
            ('start_date', '<=', year_end),
        ], order='start_date asc, id asc')

        cumulative = 0.0
        for request in requests:
            for day, weight in request._sick_leave_units():
                if day < year_start or day > year_end:
                    continue
                tier_before = cumulative
                cumulative += weight
                if not (period_start <= day <= period_end):
                    continue
                if tier_before >= SICK_MAX_PAY_CONSIDERED:
                    continue
                if tier_before + weight <= SICK_FULL_PAY_LIMIT:
                    result['full_pay_days'] += weight
                elif tier_before >= SICK_FULL_PAY_LIMIT:
                    result['half_pay_days'] += min(weight, SICK_MAX_PAY_CONSIDERED - tier_before)
                else:
                    # Straddles the Full-Pay/Half-Pay boundary within this unit.
                    full_part = SICK_FULL_PAY_LIMIT - tier_before
                    result['full_pay_days'] += full_part
                    result['half_pay_days'] += min(weight - full_part, SICK_MAX_PAY_CONSIDERED - SICK_FULL_PAY_LIMIT)
        return result

    def write(self, vals):
        protected = {k for k in vals if k not in ('state', 'balance_deducted', 'paid', 'manager_remarks', 'applied_date')}
        if protected:
            for rec in self:
                if rec.state in ('approved', 'rejected', 'cancelled'):
                    raise UserError("You cannot modify a leave request that is already approved, rejected, or cancelled.")
        return super(LeaveRequest, self).write(vals)
