from odoo import models, api, fields, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import requests
import logging

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # -------------------------------------------------
    # 🔗 DESKTIME API CALL (STRICT MODE)
    # -------------------------------------------------
    def _send_desktime_webhook(self, attendance, status, ignore_non_blocking_errors=False):
        try:
            employee = attendance.employee_id
            email = employee.work_email

            if not email:
                if ignore_non_blocking_errors:
                    _logger.warning("DeskTime: Missing email for %s", employee.name)
                    return False
                raise UserError(_("Employee %s does not have a work email configured.") % employee.name)

            if status == "check_in":
                location = f"{attendance.in_latitude},{attendance.in_longitude}"
            else:
                location = f"{attendance.out_latitude},{attendance.out_longitude}"

            payload = {
                "email": email,
                "status": status,
                "timestamp": fields.Datetime.now().isoformat(),
                "location": location,
                "odooAttendanceId": attendance.id or 0,
            }

            response = requests.post(
                "https://backend-desktime.averelabs.com/api/attendance/webhook",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )

            # ✅ SUCCESS
            if response.status_code == 200:
                return True

            # 🚫 IGNORE IN AUTO MODE
            if ignore_non_blocking_errors and response.status_code in (403, 404):
                _logger.warning(
                    "DeskTime ignored (auto checkout): %s - %s",
                    response.status_code,
                    response.text
                )
                return False

            # ❌ STRICT ERRORS
            if response.status_code == 400:
                raise UserError(_("DeskTime Error: Invalid payload."))

            elif response.status_code == 403:
                raise UserError(_("DeskTime Error: Client is not active."))

            elif response.status_code == 404:
                raise UserError(_("DeskTime Error: User not found."))

            else:
                raise UserError(_("DeskTime Error: Unexpected response (%s).") % response.status_code)

        except requests.exceptions.Timeout:
            if ignore_non_blocking_errors:
                _logger.warning("DeskTime timeout (auto checkout)")
                return False
            raise UserError(_("DeskTime server timeout."))

        except requests.exceptions.RequestException as e:
            if ignore_non_blocking_errors:
                _logger.warning("DeskTime connection failed (auto): %s", str(e))
                return False
            raise UserError(_("DeskTime connection failed: %s") % str(e))

    # -------------------------------------------------
    # CREATE (CHECK-IN)
    # -------------------------------------------------
    @api.model
    def create(self, vals):

        # 1️⃣ GPS VALIDATION
        if 'check_in' in vals and (not vals.get('in_latitude') or not vals.get('in_longitude')):
            raise UserError(_('Cannot check in without location. Please enable GPS/location services.'))

        if 'check_in' in vals and vals.get('employee_id'):

            employee_id = vals['employee_id']
            check_in = fields.Datetime.from_string(vals['check_in'])

            start_of_day = check_in.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = check_in.replace(hour=23, minute=59, second=59, microsecond=999999)

            # 2️⃣ ONE CHECK-IN PER DAY
            existing_attendance = self.search([
                ('employee_id', '=', employee_id),
                ('check_in', '>=', start_of_day),
                ('check_in', '<=', end_of_day),
            ], limit=1)

            # if existing_attendance:
            #     raise UserError(_('You have already checked in today.'))

            employee = self.env['hr.employee'].browse(employee_id)
            user_id = employee.user_id.id if employee.user_id else False

            if not user_id:
                raise UserError(_('Employee %s is not linked to a user.') % employee.name)

            # 3️⃣ TIMESHEET VALIDATION
            start_of_month = check_in.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            previous_attendances = self.search([
                ('employee_id', '=', employee_id),
                ('check_in', '>=', start_of_month),
                ('check_in', '<', check_in)
            ])

            attendance_dates = set(att.check_in.date() for att in previous_attendances if att.check_in)

            timesheet_model = self.env['account.analytic.line']
            missing_critical = []
            missing_grace = []

            today = check_in.date()
            grace_days = 2

            for att_date in sorted(attendance_dates):

                day_attendances = self.search([
                    ('employee_id', '=', employee_id),
                    ('check_in', '>=', datetime.combine(att_date, datetime.min.time())),
                    ('check_in', '<=', datetime.combine(att_date, datetime.max.time())),
                ])

                total_worked_hours = sum(day_attendances.mapped('worked_hours'))

                if total_worked_hours <= 0:
                    continue

                timesheet_lines = timesheet_model.search([
                    ('user_id', '=', user_id),
                    ('date', '=', att_date),
                    ('unit_amount', '>', 0)
                ])

                total_timesheet_hours = sum(timesheet_lines.mapped('unit_amount'))
                required_hours = total_worked_hours * 0.8

                if total_timesheet_hours < required_hours:

                    days_diff = (today - att_date).days
                    formatted_date = att_date.strftime('%Y-%m-%d')

                    line = f"{formatted_date} (Filled: {total_timesheet_hours:.2f}h / Required: {required_hours:.2f}h)"

                    if days_diff > grace_days:
                        missing_critical.append(line)
                    else:
                        missing_grace.append(line)

            if missing_critical:
                message = _("Cannot check in due to insufficient timesheet entries.\n\n")
                message += _("❌ Below 80%% beyond grace:\n%s\n") % ("\n".join(missing_critical))

                if missing_grace:
                    message += _("\n⚠️ Within grace:\n%s") % ("\n".join(missing_grace))

                raise UserError(message)

        # 🔗 CALL API BEFORE SAVE (BLOCKING)
        if vals.get('check_in'):
            temp_record = self.new(vals)
            self._send_desktime_webhook(temp_record, "check_in")

        record = super().create(vals)
        return record

    # -------------------------------------------------
    # WRITE (CHECK-OUT)
    # -------------------------------------------------
    def write(self, vals):

        for attendance in self:
            if vals.get('check_out'):

                # GPS VALIDATION
                if not vals.get('out_latitude') or not vals.get('out_longitude'):
                    raise UserError(_('Cannot check out without location.'))

                # 🔗 CALL API BEFORE WRITE (BLOCKING)
                temp_vals = attendance.copy_data()[0]
                temp_vals.update(vals)

                temp_record = self.new(temp_vals)
                self._send_desktime_webhook(temp_record, "check_out")

        return super().write(vals)

    # -------------------------------------------------
    # AUTO CHECKOUT AFTER 12 HOURS
    # -------------------------------------------------
    @api.model
    def auto_checkout_old_attendances(self):

        twelve_hours_ago = fields.Datetime.now() - timedelta(hours=12)

        open_attendances = self.search([
            ('check_in', '<=', twelve_hours_ago),
            ('check_out', '=', False)
        ])

        for att in open_attendances:
            default_checkout = att.check_in + timedelta(hours=12)

            vals = {
                'check_out': default_checkout,
                'out_latitude': att.in_latitude or 0.0,
                'out_longitude': att.in_longitude or 0.0,
            }

            # 🔗 BLOCKING API CALL
            temp_vals = att.copy_data()[0]
            temp_vals.update(vals)

            temp_record = self.new(temp_vals)
            self._send_desktime_webhook(temp_record, "check_out", ignore_non_blocking_errors=True)

            # ONLY WRITE IF API SUCCESS
            att.write(vals)

        return True

    # -------------------------------------------------
    # FORGOT LOGOUT ACTION
    # -------------------------------------------------
    def action_forgot_logout(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Forgot to Logout',
            'res_model': 'forgot.logout.wizard',
            'view_mode': 'form',
            'target': 'new',
        }