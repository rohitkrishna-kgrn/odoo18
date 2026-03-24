from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import timedelta

class LeaveRequest(models.Model):
    _name = 'leave.request'
    _description = 'Leave Request'

    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, required=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    start_date = fields.Date(string='Start Date', required=True)
    end_date = fields.Date(string='End Date', required=True)
    days_requested = fields.Integer(string='Days Requested', compute='_compute_days_requested', store=True)
    reason = fields.Text(string='Reason')
    attachment = fields.Binary(string='Attachment')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status')
    paid = fields.Boolean(string='Paid Leave')
    balance_deducted = fields.Boolean(string='Balance Deducted', default=False)
    available_balance = fields.Float(
        string="Available Balance",
        compute='_compute_available_balance',
        store=False  # Don't store since it changes monthly
    )

    @api.depends('user_id', 'leave_type_id', 'start_date')
    def _compute_available_balance(self):
        LeaveBalance = self.env['leave.balance']
        for rec in self:
            rec.available_balance = 0.0
            if rec.user_id and rec.leave_type_id and rec.start_date:
                first_of_month = rec.start_date.replace(day=1)
                balance_record = LeaveBalance.search([
                    ('user_id', '=', rec.user_id.id),
                    ('leave_type_id', '=', rec.leave_type_id.id),
                    ('date', '=', first_of_month),
                ], limit=1)
                rec.available_balance = balance_record.balance if balance_record else 0.0


    @api.depends('start_date', 'end_date')
    def _compute_days_requested(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                rec.days_requested = (rec.end_date - rec.start_date).days + 1
            else:
                rec.days_requested = 0

    def action_request(self):
        for rec in self:
            if not rec.leave_type_id:
                raise UserError("Please select a Leave Type.")

            LeaveBalance = self.env['leave.balance']
            first_of_month = fields.Date.today().replace(day=1)

            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('date', '=', first_of_month)
            ], limit=1)

            current_balance = balance_record.balance if balance_record else 0

            if rec.days_requested > current_balance:
                raise UserError(
                    f"You do not have enough leave balance for {rec.leave_type_id.name}. "
                    f"Available: {current_balance}, Requested: {rec.days_requested}"
                )

            rec.state = 'requested'

    def action_open_approve_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Approve Leave',
            'res_model': 'leave.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id}
        }

    # --- Reject and restore balance if deducted ---
    def action_reject(self):
        for rec in self:
            if rec.state == 'approved' and rec.paid and rec.balance_deducted:
                LeaveBalance = self.env['leave.balance']
                first_of_month = rec.start_date.replace(day=1)

                balance_record = LeaveBalance.search([
                    ('user_id', '=', rec.user_id.id),
                    ('leave_type_id', '=', rec.leave_type_id.id),
                    ('date', '=', first_of_month)
                ], limit=1)

                if balance_record:
                    balance_record.balance += rec.days_requested

                rec.balance_deducted = False

            rec.state = 'rejected'

    def write(self, vals):
        for rec in self:
            if rec.state in ['approved', 'rejected']:
                raise UserError("You cannot modify a leave request that is already approved or rejected.")
        return super(LeaveRequest, self).write(vals)