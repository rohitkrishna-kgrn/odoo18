from odoo import models, fields, api
from odoo.exceptions import UserError

from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor

class AddCompLeaveWizard(models.TransientModel):
    _name = 'add.comp.leave.wizard'
    _description = 'Add Compensation Leave Wizard'

    user_id = fields.Many2one('res.users', string='User', required=True)
    days = fields.Float(string='Days to Add', required=True)

    def action_add_comp_leave(self):
        LeaveType = self.env['leave.type']
        LeaveBalance = self.env['leave.balance']

        comp_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)
        if not comp_leave:
            raise UserError("Compensation Leave type is not defined!")

        first_of_month = leave_month_anchor(fields.Date.today())

        balance_record = LeaveBalance.search([
            ('user_id', '=', self.user_id.id),
            ('leave_type_id', '=', comp_leave.id),
            ('date', '=', first_of_month)
        ], limit=1)

        if balance_record:
            balance_record.balance += self.days
        else:
            LeaveBalance.create({
                'user_id': self.user_id.id,
                'leave_type_id': comp_leave.id,
                'date': first_of_month,
                'balance': self.days
            })

        return {'type': 'ir.actions.act_window_close'}
