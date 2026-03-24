from odoo import models, api, fields, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    @api.model
    def create(self, vals):

        # -------------------------------------------------
        # 1️⃣ GPS VALIDATION FOR CHECK-IN
        # -------------------------------------------------
        if 'check_in' in vals and (not vals.get('in_latitude') or not vals.get('in_longitude')):
            raise UserError(_('Cannot check in without location. Please enable GPS/location services.'))

        if 'check_in' in vals and vals.get('employee_id'):

            employee_id = vals['employee_id']
            check_in = fields.Datetime.from_string(vals['check_in'])

            start_of_day = check_in.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = check_in.replace(hour=23, minute=59, second=59, microsecond=999999)

            # -------------------------------------------------
            # 2️⃣ ONE CHECK-IN PER DAY
            # -------------------------------------------------
            existing_attendance = self.search([
                ('employee_id', '=', employee_id),
                ('check_in', '>=', start_of_day),
                ('check_in', '<=', end_of_day),
            ], limit=1)

            if existing_attendance:
                raise UserError(_('You have already checked in today. Only one check-in allowed per day.'))

            employee = self.env['hr.employee'].browse(employee_id)
            user_id = employee.user_id.id if employee.user_id else False

            if not user_id:
                raise UserError(_('Employee %s is not linked to a user. Cannot validate timesheets.') % employee.name)

            # -------------------------------------------------
            # 3️⃣ TIMESHEET 80% + GRACE VALIDATION
            # -------------------------------------------------
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
            grace_days = 2  # You can change this

            for att_date in sorted(attendance_dates):

                # All attendances for that date
                day_attendances = self.search([
                    ('employee_id', '=', employee_id),
                    ('check_in', '>=', datetime.combine(att_date, datetime.min.time())),
                    ('check_in', '<=', datetime.combine(att_date, datetime.max.time())),
                ])

                total_worked_hours = sum(day_attendances.mapped('worked_hours'))

                if total_worked_hours <= 0:
                    continue

                # Timesheet hours
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

                    line = (
                        f"{formatted_date} "
                        f"(Filled: {total_timesheet_hours:.2f}h / "
                        f"Required: {required_hours:.2f}h)"
                    )

                    if days_diff > grace_days:
                        missing_critical.append(line)
                    else:
                        missing_grace.append(line)

            # 🚨 BLOCK only if critical exists
            if missing_critical:
                message = _("Cannot check in due to insufficient timesheet entries.\n\n")
                message += _("❌ Below 80%% coverage beyond grace period (Attendance Blocked):\n%s\n") % (
                    "\n".join(missing_critical)
                )

                # Still show grace warnings
                if missing_grace:
                    message += _("\n⚠️ Below 80%% but within grace period:\n%s") % (
                        "\n".join(missing_grace)
                    )

                raise UserError(message)

        return super().create(vals)

    # -------------------------------------------------
    # 4️⃣ GPS VALIDATION FOR CHECK-OUT
    # -------------------------------------------------
    def write(self, vals):
        for attendance in self:
            if vals.get('check_out'):
                if not vals.get('out_latitude') or not vals.get('out_longitude'):
                    raise UserError(_('Cannot check out without location. Please enable GPS/location services.'))
        return super().write(vals)

    # -------------------------------------------------
    # 5️⃣ AUTO CHECKOUT AFTER 12 HOURS
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

            att.write({
                'check_out': default_checkout,
                'out_latitude': att.in_latitude or 0.0,
                'out_longitude': att.in_longitude or 0.0,
            })

        return True

    def action_forgot_logout(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Forgot to Logout',
            'res_model': 'forgot.logout.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
