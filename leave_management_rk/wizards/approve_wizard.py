from odoo import models, fields, api
from odoo.exceptions import UserError


class LeaveApprovalWizard(models.TransientModel):
    _name = 'leave.approval.wizard'
    _description = 'Leave Approval Wizard'

    leave_id = fields.Many2one('leave.request', string='Leave Request', required=True)
    paid = fields.Boolean(string='Paid Leave')

    def action_approve(self):
        self.ensure_one()

        leave = self.leave_id

        if leave.state != 'requested':
            raise UserError("Only leave requests in 'Requested' state can be approved.")

        # Update paid flag
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
