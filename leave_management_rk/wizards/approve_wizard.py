from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import date


class LeaveApprovalWizardBalanceLine(models.TransientModel):
    _name = 'leave.approval.wizard.balance.line'
    _description = 'Leave Approval Wizard Balance Line'

    wizard_id = fields.Many2one('leave.approval.wizard', string='Wizard')
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', readonly=True)
    balance = fields.Float(string='Balance', readonly=True)
    unit = fields.Char(string='Unit', compute='_compute_unit')

    @api.depends('leave_type_id')
    def _compute_unit(self):
        for rec in self:
            rec.unit = 'hrs' if (rec.leave_type_id and rec.leave_type_id.is_permission) else 'days'


class LeaveApprovalWizard(models.TransientModel):
    _name = 'leave.approval.wizard'
    _description = 'Leave Approval Wizard'

    leave_id = fields.Many2one('leave.request', string='Leave Request', required=True)
    paid = fields.Boolean(string='Paid Leave')
    is_permission = fields.Boolean(compute='_compute_is_permission', store=False)
    balance_line_ids = fields.One2many(
        'leave.approval.wizard.balance.line', 'wizard_id',
        string='Employee Leave Balances'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        leave_id = res.get('leave_id') or self.env.context.get('default_leave_id')
        if leave_id:
            leave = self.env['leave.request'].browse(leave_id)
            if leave.exists() and leave.user_id:
                first_of_month = date.today().replace(day=1)
                balances = self.env['leave.balance'].search([
                    ('user_id', '=', leave.user_id.id),
                    ('date', '=', first_of_month),
                ])
                lines = []
                for b in balances:
                    lines.append((0, 0, {
                        'leave_type_id': b.leave_type_id.id,
                        'balance': b.balance,
                    }))
                res['balance_line_ids'] = lines
        return res

    @api.depends('leave_id')
    def _compute_is_permission(self):
        for rec in self:
            rec.is_permission = bool(
                rec.leave_id and rec.leave_id.leave_type_id and rec.leave_id.leave_type_id.is_permission
            )

    def action_approve(self):
        self.ensure_one()
        leave = self.leave_id

        if leave.state != 'requested':
            raise UserError("Only leave requests in 'Requested' state can be approved.")

        if leave.leave_type_id.is_permission:
            LeaveBalance = self.env['leave.balance']
            first_of_month = leave.start_date.replace(day=1)
            balance_record = LeaveBalance.search([
                ('user_id', '=', leave.user_id.id),
                ('leave_type_id', '=', leave.leave_type_id.id),
                ('date', '=', first_of_month)
            ], limit=1)
            if not balance_record:
                raise UserError("Permission balance record not found.")
            if leave.hours_requested > balance_record.balance:
                raise UserError(
                    f"Insufficient permission hours. Available: {balance_record.balance} hrs, "
                    f"Requested: {leave.hours_requested} hrs"
                )
            if not leave.balance_deducted:
                balance_record.balance -= leave.hours_requested
                leave.balance_deducted = True
            leave.paid = False
        else:
            leave.paid = self.paid
            if self.paid:
                LeaveBalance = self.env['leave.balance']
                first_of_month = leave.start_date.replace(day=1)
                balance_record = LeaveBalance.search([
                    ('user_id', '=', leave.user_id.id),
                    ('leave_type_id', '=', leave.leave_type_id.id),
                    ('date', '=', first_of_month)
                ], limit=1)
                if not balance_record:
                    raise UserError("Leave balance record not found.")
                if leave.days_requested > balance_record.balance:
                    raise UserError(
                        f"Insufficient leave balance for {leave.leave_type_id.name}. "
                        f"Available: {balance_record.balance}, Requested: {leave.days_requested}"
                    )
                if not leave.balance_deducted:
                    balance_record.balance -= leave.days_requested
                    leave.balance_deducted = True

        leave.state = 'approved'
