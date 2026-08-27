from odoo import models, fields


class TimesheetComplianceWizard(models.TransientModel):
    """Generate the compliance reports for any week on demand.

    Exists mainly so the figures can be checked against a week that is already
    over (or re-run after someone backfills their timesheets) without waiting
    for Monday. Sending is off by default - the normal use is to look at the
    numbers on screen first."""
    _name = 'timesheet.compliance.wizard'
    _description = 'Generate Timesheet Compliance Reports for a Week'

    week_date = fields.Date(
        string='Any Date In The Week', required=True,
        default=fields.Date.context_today,
        help="The report covers the full Monday-to-Sunday week containing this "
             "date. Picking any day of that week gives the same result.")
    manager_ids = fields.Many2many(
        'hr.employee', string='Only These Managers',
        help="Leave empty to generate a report for every manager who has "
             "someone pointing at them in the Manager field on the Employee "
             "form. Set one or more to test a single team.")
    send_email = fields.Boolean(
        string='Also Email Each Manager', default=False,
        help="Off by default. When ticked, every generated report is emailed "
             "to its own manager - exactly what the Monday cron does.")

    def action_generate(self):
        self.ensure_one()
        reports = self.env['timesheet.compliance.report']._generate_for_week(
            self.week_date,
            send_email=self.send_email,
            managers=self.manager_ids or None)
        return {
            'type': 'ir.actions.act_window',
            'name': 'Timesheet Compliance',
            'res_model': 'timesheet.compliance.report',
            'view_mode': 'list,form',
            'domain': [('id', 'in', reports.ids)],
            'target': 'current',
        }
