from collections import defaultdict
from datetime import datetime

from pytz import UTC, timezone

from odoo import api, models

from odoo.addons.leave_management_rk.models.hr_attendance_inherit import GRACE_DAYS_PER_PERIOD
from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor, leave_month_bounds

from .perf import scope_cache

DUBAI_TZ = timezone('Asia/Dubai')


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model
    def _late_checkin_permission_hours(self, user, date_worked):
        """Same result as leave_management_rk; inside a payroll operation the user's
        approved permission leaves are read once instead of once per check-in."""
        cache = scope_cache()
        if cache is None or not user:
            return super()._late_checkin_permission_hours(user, date_worked)
        key = ('permission_hours', user.id)
        if key not in cache:
            hours = defaultdict(float)
            for leave in self.env['leave.request'].search([
                    ('user_id', '=', user.id),
                    ('state', '=', 'approved'),
                    ('leave_type_id.is_permission', '=', True)]):
                hours[leave.start_date] += leave.hours_requested
            cache[key] = hours
        return cache[key].get(date_worked, 0.0)

    @api.model
    def get_late_login_grace_status(self, employee, check_in_dubai):
        """Same result as leave_management_rk; inside a payroll operation the late days
        of an employee's 26th -> 25th period are worked out once, not once per late day."""
        cache = scope_cache()
        if cache is None:
            return super().get_late_login_grace_status(employee, check_in_dubai)
        date_worked = check_in_dubai.date()
        period_start, period_end = leave_month_bounds(leave_month_anchor(date_worked))
        key = ('late_dates', employee.id, period_start)
        if key not in cache:
            late_dates = set()
            for att in self.search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '>=', datetime.combine(period_start, datetime.min.time())),
                    ('check_in', '<=', datetime.combine(period_end, datetime.max.time()))]):
                if not att.check_in:
                    continue
                att_dubai = att.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)
                if self._is_late_checkin(employee, att_dubai):
                    late_dates.add(att_dubai.date())
            cache[key] = sorted(late_dates)
        ordered = cache[key]
        ordinal = ordered.index(date_worked) + 1 if date_worked in ordered else len(ordered) + 1
        return ordinal, ordinal > GRACE_DAYS_PER_PERIOD
