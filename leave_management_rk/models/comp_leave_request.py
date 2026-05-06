from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import date


class LeaveCompRequest(models.Model):
    _name = 'leave.comp.request'
    _description = 'Compensation Leave Request'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='Employee', default=lambda self: self.env.user, required=True)
    date_worked = fields.Date(string='Date Worked / Overtime Date', required=True)
    days = fields.Float(string='Days to Compensate', default=1.0, required=True)
    reason = fields.Text(string='Reason / Description')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status')

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft requests can be submitted.")
            if rec.days <= 0:
                raise UserError("Days must be greater than 0.")
            rec.state = 'requested'

    def action_approve(self):
        for rec in self:
            if rec.state != 'requested':
                raise UserError("Only submitted requests can be approved.")
            LeaveType = self.env['leave.type']
            LeaveBalance = self.env['leave.balance']
            comp_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)
            if not comp_leave:
                raise UserError("Compensation Leave type not found. Please configure it first.")
            today = date.today()
            first_of_month = today.replace(day=1)
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', comp_leave.id),
                ('date', '=', first_of_month)
            ], limit=1)
            if balance_record:
                balance_record.balance += rec.days
            else:
                LeaveBalance.create({
                    'user_id': rec.user_id.id,
                    'leave_type_id': comp_leave.id,
                    'date': first_of_month,
                    'balance': rec.days,
                })
            rec.state = 'approved'

    def action_reject(self):
        for rec in self:
            if rec.state not in ('draft', 'requested'):
                raise UserError("Cannot reject an already approved or rejected request.")
            rec.state = 'rejected'
