from odoo import models, api, fields
from datetime import timedelta
from pytz import timezone, UTC

DUBAI_TZ = timezone('Asia/Dubai')


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

    @api.depends('check_in')
    def _compute_check_in_dubai(self):
        for rec in self:
            if rec.check_in:
                dubai_dt = rec.check_in.replace(tzinfo=UTC).astimezone(DUBAI_TZ)
                rec.check_in_dubai = dubai_dt.strftime('%d %b %Y %I:%M %p')
            else:
                rec.check_in_dubai = ''

    @api.depends('check_in', 'employee_id')
    def _compute_login_status(self):
        LeaveRequest = self.env['leave.request']
        for rec in self:
            if not rec.check_in:
                rec.is_late_login = False
                rec.login_status = ''
                continue

            check_in_utc = rec.check_in.replace(tzinfo=UTC)
            check_in_dubai = check_in_utc.astimezone(DUBAI_TZ)
            deadline = check_in_dubai.replace(hour=8, minute=50, second=0, microsecond=0)

            if check_in_dubai <= deadline:
                rec.is_late_login = False
                rec.login_status = 'Valid Login'
                continue

            # Checked in after 8:50 AM — look for approved permission on this date
            user = rec.employee_id.user_id
            date_worked = check_in_dubai.date()
            permission_hours = 0.0

            if user:
                permissions = LeaveRequest.search([
                    ('user_id', '=', user.id),
                    ('state', '=', 'approved'),
                    ('leave_type_id.is_permission', '=', True),
                    ('start_date', '=', date_worked),
                ])
                permission_hours = sum(permissions.mapped('hours_requested'))

            extended_deadline = deadline + timedelta(hours=permission_hours)

            if check_in_dubai > extended_deadline:
                rec.is_late_login = True
                rec.login_status = 'Late Login (0.5 day deducted)'
            else:
                rec.is_late_login = False
                rec.login_status = 'Valid Login (with permission)'

    def name_get(self):
        result = []
        for rec in self:
            if rec.check_in:
                label = rec.check_in.strftime('%A, %d %b %Y')
            else:
                label = f'Attendance #{rec.id}'
            result.append((rec.id, label))
        return result
