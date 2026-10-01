from odoo import models, fields, api
from odoo.exceptions import UserError

from odoo.addons.leave_management_rk.models.leave_period import (
    leave_month_label as format_leave_month,
)


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
    leave_month_label = fields.Char(string='Leave Month', readonly=True)
    paid = fields.Boolean(
        string='Paid Leave', default=True,
        help="Whether Payroll treats this leave as compensated (Paid Leave) "
             "or unpaid (Loss of Pay) time off. Purely a payroll setting - "
             "the leave balance is always deducted on approval regardless "
             "of this, the same as any other approved leave.")
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
                first_of_month = leave._balance_anchor()
                res['leave_month_label'] = format_leave_month(first_of_month)
                # Only leave types actually applicable to this employee's
                # country (same domain as the Employee Leave Balance wizard)
                # - never a stray/legacy leave.balance row for a type that
                # no longer applies to them (e.g. after a country change).
                applicable_types = self.env['leave.type'].search([
                    '|', ('country_scope', '=', False), ('country_scope', '=', leave.user_id.country),
                ])
                balances = self.env['leave.balance'].search([
                    ('user_id', '=', leave.user_id.id),
                    ('date', '=', first_of_month),
                    ('leave_type_id', 'in', applicable_types.ids),
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

        if leave.state != 'manager_approved':
            raise UserError("Only manager-approved leave requests can be approved here.")

        if leave.leave_type_id.is_permission:
            LeaveBalance = self.env['leave.balance']
            first_of_month = leave._balance_anchor()
            balance_record = LeaveBalance.search([
                ('user_id', '=', leave.user_id.id),
                ('leave_type_id', '=', leave.leave_type_id.id),
                ('date', '=', first_of_month)
            ], limit=1)
            if not balance_record:
                balance_record = LeaveBalance._ensure_permission_row(
                    leave.user_id, leave.leave_type_id, first_of_month)
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
            # Balance is always deducted for an approved leave - "paid" only
            # controls how Payroll categorises it (see the field's help),
            # it must never gate whether the leave balance itself moves.
            leave.paid = self.paid
            LeaveBalance = self.env['leave.balance']
            first_of_month = leave._balance_anchor()
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
