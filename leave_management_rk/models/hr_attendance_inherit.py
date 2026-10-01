from datetime import datetime, timedelta
from pytz import timezone, UTC

from odoo import models, api, fields

from .leave_period import leave_month_anchor, leave_month_bounds

DUBAI_TZ = timezone('Asia/Dubai')

# Late-login grace period: the first GRACE_DAYS_PER_PERIOD late check-ins in
# an employee's attendance period (26th -> 25th, see leave_period.py) are
# excused and shown as "Grace Day - N"; the existing 0.5-day deduction only
# kicks in from the (GRACE_DAYS_PER_PERIOD + 1)'th late check-in onwards.
# Shared by om_hr_payroll's late-login deduction so Attendance and Payroll
# never disagree on which check-ins were excused.
GRACE_DAYS_PER_PERIOD = 4


class HrAttendanceInherit(models.Model):
    _inherit = 'hr.attendance'

    is_late_login = fields.Boolean(
        string='Late Login', compute='_compute_login_status', store=False
    )
    login_status = fields.Char(
        string='Login Status', compute='_compute_login_status', store=False
    )
    check_in_dubai = fields.Char(
        string='Check-In (Dubai Time)', compute='_compute_check_in_dubai', store=False
    )
    attendance_period_anchor = fields.Date(
        string='Attendance Period', compute='_compute_attendance_period_anchor', store=True,
        help="First day of the calendar month this attendance's 26th->25th "
             "attendance period is named after (see leave_period.py) — grouping "
             "by this field, not check_in, shows 'month wise' data for the "
             "26th-to-25th period instead of the calendar month."
    )

    @api.depends('check_in')
    def _compute_check_in_dubai(self):
        for rec in self:
            if rec.check_in:
                dubai_dt = rec.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)
                rec.check_in_dubai = dubai_dt.strftime('%d %b %Y %I:%M %p')
            else:
                rec.check_in_dubai = ''

    @api.depends('check_in')
    def _compute_attendance_period_anchor(self):
        for rec in self:
            if rec.check_in:
                check_in_dubai = rec.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)
                rec.attendance_period_anchor = leave_month_anchor(check_in_dubai.date())
            else:
                rec.attendance_period_anchor = False

    @api.model
    def _late_checkin_permission_hours(self, user, date_worked):
        """Approved-permission hours that push back the 8:50 AM deadline for
        `user` on `date_worked`."""
        if not user:
            return 0.0
        permissions = self.env['leave.request'].search([
            ('user_id', '=', user.id),
            ('state', '=', 'approved'),
            ('leave_type_id.is_permission', '=', True),
            ('start_date', '=', date_worked),
        ])
        return sum(permissions.mapped('hours_requested'))

    @api.model
    def _is_late_checkin(self, employee, check_in_dubai):
        """True if a tz-aware (Asia/Dubai) check-in counts as late: after
        8:50 AM plus any approved-permission extension for that day."""
        deadline = check_in_dubai.replace(hour=8, minute=50, second=0, microsecond=0)
        if check_in_dubai <= deadline:
            return False
        permission_hours = self._late_checkin_permission_hours(employee.user_id, check_in_dubai.date())
        return check_in_dubai > deadline + timedelta(hours=permission_hours)

    @api.model
    def get_late_login_grace_status(self, employee, check_in_dubai):
        """For an already-late check-in by `employee` at tz-aware
        `check_in_dubai`, return (ordinal, is_deducted).

        `ordinal` is this check-in's 1-based rank, by date, among the
        employee's late check-ins within its 26th -> 25th attendance
        period (see leave_period.py). Deduction only applies once
        `ordinal` exceeds GRACE_DAYS_PER_PERIOD; the first
        GRACE_DAYS_PER_PERIOD are excused as grace days.
        """
        date_worked = check_in_dubai.date()
        period_start, period_end = leave_month_bounds(leave_month_anchor(date_worked))

        period_attendances = self.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', datetime.combine(period_start, datetime.min.time())),
            ('check_in', '<=', datetime.combine(period_end, datetime.max.time())),
        ])

        late_dates = set()
        for att in period_attendances:
            if not att.check_in:
                continue
            att_check_in_dubai = att.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)
            if self._is_late_checkin(employee, att_check_in_dubai):
                late_dates.add(att_check_in_dubai.date())

        ordered_late_dates = sorted(late_dates)
        if date_worked in ordered_late_dates:
            ordinal = ordered_late_dates.index(date_worked) + 1
        else:
            # date_worked itself wasn't found among period_attendances (e.g.
            # called before the record is committed) — treat it as the next
            # late check-in of the period.
            ordinal = len(ordered_late_dates) + 1

        return ordinal, ordinal > GRACE_DAYS_PER_PERIOD

    @api.depends('check_in', 'employee_id')
    def _compute_login_status(self):
        for rec in self:
            if not rec.check_in:
                rec.is_late_login = False
                rec.login_status = ''
                continue

            check_in_utc = rec.check_in.replace(tzinfo=UTC)
            check_in_dubai = check_in_utc.astimezone(DUBAI_TZ)
            deadline = check_in_dubai.replace(hour=8, minute=50, second=0, microsecond=0)

            if not rec._is_late_checkin(rec.employee_id, check_in_dubai):
                rec.is_late_login = False
                rec.login_status = 'Valid Login' if check_in_dubai <= deadline else 'Valid Login (with permission)'
                continue

            ordinal, is_deducted = rec.get_late_login_grace_status(rec.employee_id, check_in_dubai)
            if is_deducted:
                rec.is_late_login = True
                rec.login_status = 'Late Login (0.5 day deducted)'
            else:
                rec.is_late_login = False
                rec.login_status = 'Grace Day - %d' % ordinal

    def name_get(self):
        result = []
        for rec in self:
            if rec.check_in:
                label = rec.check_in.strftime('%A, %d %b %Y')
            else:
                label = f'Attendance #{rec.id}'
            result.append((rec.id, label))
        return result
