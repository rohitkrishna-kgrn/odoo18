from odoo import models, fields

from .leave_period import leave_month_bounds

class ResUsers(models.Model):
    _inherit = 'res.users'

    country = fields.Selection([
        ('india', 'India'),
        ('dubai', 'Dubai'),
    ], string='Country For Leave Model')

    def took_leave(self, leave_type, month_date):
        LeaveRequest = self.env['leave.request']
        # month_date is a leave-month anchor; the real window it covers runs
        # from the 26th of the previous month to the 25th of this one.
        start_date, end_date = leave_month_bounds(month_date)

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
