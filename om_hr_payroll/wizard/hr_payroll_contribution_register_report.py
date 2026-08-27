from datetime import datetime
from dateutil import relativedelta

from odoo import api, fields, models
from odoo.addons.leave_management_rk.models.leave_period import current_leave_month_bounds


class PayslipLinesContributionRegister(models.TransientModel):
    _name = 'payslip.lines.contribution.register'
    _description = 'Payslip Lines by Contribution Registers'

    date_from = fields.Date(string='Date From', required=True,
        default=lambda self: current_leave_month_bounds()[0])
    date_to = fields.Date(string='Date To', required=True,
        default=lambda self: current_leave_month_bounds()[1])

    def print_report(self):
        active_ids = self.env.context.get('active_ids', [])
        datas = {
             'ids': active_ids,
             'model': 'hr.contribution.register',
             'form': self.read()[0]
        }
        return self.env.ref('om_om_hr_payroll.action_contribution_register').report_action([], data=datas)
