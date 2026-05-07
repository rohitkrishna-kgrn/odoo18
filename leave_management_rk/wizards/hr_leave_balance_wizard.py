from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import date


class HrLeaveBalanceWizard(models.TransientModel):
    _name = 'hr.leave.balance.wizard'
    _description = 'HR Leave Balance Management'

    user_id = fields.Many2one('res.users', string='Employee', required=True)
    line_ids = fields.One2many('hr.leave.balance.wizard.line', 'wizard_id', string='Leave Balances')

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if not self.user_id:
            self.line_ids = [(5, 0, 0)]
            return

        today = date.today()
        first_of_month = today.replace(day=1)
        LeaveBalance = self.env['leave.balance']
        LeaveType = self.env['leave.type']

        lines = []
        for lt in LeaveType.search([], order='name'):
            balance_rec = LeaveBalance.search([
                ('user_id', '=', self.user_id.id),
                ('leave_type_id', '=', lt.id),
                ('date', '=', first_of_month),
            ], limit=1)
            lines.append((0, 0, {
                'leave_type_id': lt.id,
                'balance': balance_rec.balance if balance_rec else 0.0,
            }))
        self.line_ids = lines

    def action_save(self):
        if not self.user_id:
            raise UserError("Please select an employee.")

        today = date.today()
        first_of_month = today.replace(day=1)
        LeaveBalance = self.env['leave.balance']

        for line in self.line_ids:
            if not line.leave_type_id:
                continue
            balance_rec = LeaveBalance.search([
                ('user_id', '=', self.user_id.id),
                ('leave_type_id', '=', line.leave_type_id.id),
                ('date', '=', first_of_month),
            ], limit=1)
            if balance_rec:
                balance_rec.balance = line.balance
            else:
                LeaveBalance.create({
                    'user_id': self.user_id.id,
                    'leave_type_id': line.leave_type_id.id,
                    'date': first_of_month,
                    'balance': line.balance,
                })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saved',
                'message': f'Leave balances updated for {self.user_id.name}.',
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def action_reset_all_leaves(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only System Administrators can reset leave balances.")
        return self.env['leave.balance'].action_manual_reset_leaves()


class HrLeaveBalanceWizardLine(models.TransientModel):
    _name = 'hr.leave.balance.wizard.line'
    _description = 'Leave Balance Wizard Line'

    wizard_id = fields.Many2one('hr.leave.balance.wizard', string='Wizard')
    leave_type_id = fields.Many2one('leave.type', string='Leave Type')
    is_permission = fields.Boolean(related='leave_type_id.is_permission', readonly=True)
    balance = fields.Float(string='Balance')
    balance_label = fields.Char(string='Unit', compute='_compute_balance_label')

    @api.depends('is_permission')
    def _compute_balance_label(self):
        for rec in self:
            rec.balance_label = 'hrs' if rec.is_permission else 'days'
