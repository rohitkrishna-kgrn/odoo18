from odoo import models, fields, api
from datetime import datetime, time
import logging

_logger = logging.getLogger(__name__)


class ForgotLogoutWizard(models.TransientModel):
    _name = "forgot.logout.wizard"
    _description = "Forgot to Logout Wizard"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        default=lambda self: self.env.user.employee_id.id,
    )

    date = fields.Date(string="Date", required=True)
    time_spent = fields.Float(string="Extra Hours")

    @api.onchange("date")
    def _onchange_date(self):
        _logger.info("Onchange triggered for date: %s", self.date)

        if self.date and self.employee_id:
            attendances = self.env["hr.attendance"].search([
                ("employee_id", "=", self.employee_id.id),
                ("check_in", ">=", datetime.combine(self.date, time.min)),
                ("check_in", "<=", datetime.combine(self.date, time.max)),
            ])

            _logger.info("Attendances found: %s", attendances)

            extra_hours = 0.0
            for att in attendances:
                _logger.info("Attendance worked hours: %s", att.worked_hours)
                if att.worked_hours:
                    extra_hours += att.worked_hours

            self.time_spent = extra_hours
            _logger.info("Calculated extra hours: %s", self.time_spent)

    def action_submit(self):
        _logger.info("Submit button clicked")

        for rec in self:
            _logger.info("Record values - Employee: %s, Date: %s, Hours: %s",
                         rec.employee_id.name, rec.date, rec.time_spent)

            if not rec.time_spent or rec.time_spent <= 0:
                _logger.warning("No extra hours found. Closing wizard.")
                return {'type': 'ir.actions.act_window_close'}

            try:
                line = self.env["account.analytic.line"].sudo().create({
                    "name": "Forgot to logout",
                    "employee_id": rec.employee_id.id,
                    "date": rec.date,
                    "unit_amount": rec.time_spent,
                })

                _logger.info("Timesheet created successfully: %s", line.id)

            except Exception as e:
                _logger.error("Error while creating timesheet: %s", e)
                raise

        return {'type': 'ir.actions.act_window_close'}
