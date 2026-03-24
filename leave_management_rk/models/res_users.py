from odoo import models, fields
from datetime import timedelta

class ResUsers(models.Model):
    _inherit = 'res.users'

    country = fields.Selection([
        ('india', 'India'),
        ('dubai', 'Dubai'),
    ], string='Country For Leave Model')

    def took_leave(self, leave_type, month_date):
        LeaveRequest = self.env['leave.request']
        start_date = month_date
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1, day=1) - timedelta(days=1)

        leave_taken = LeaveRequest.search([
            ('user_id', '=', self.id),
            ('leave_type_id', '=', leave_type.id),
            ('start_date', '>=', start_date),
            ('end_date', '<=', end_date),
            ('state', '=', 'approved')
        ])
        return bool(leave_taken)

    def write(self, vals):
        if 'country' in vals:
            for user in self:
                if user.country != vals['country']:
                    result = super(ResUsers, user).write(vals)
                    LeaveBalance = self.env['leave.balance']
                    LeaveBalance.update_user_balance_on_country_change(user)
                    self.env.invalidate_all()
                    return result
        return super().write(vals)
