from odoo import models, fields
from odoo.exceptions import UserError


class LeaveManagerRejectWizard(models.TransientModel):
    _name = 'leave.manager.reject.wizard'
    _description = 'Manager Leave Rejection Wizard'

    leave_id = fields.Many2one('leave.request', string='Leave Request')
    comp_leave_id = fields.Many2one('leave.comp.request', string='Comp Leave Request')
    remarks = fields.Text(string='Rejection Reason', required=True)

    def action_reject(self):
        self.ensure_one()
        if not self.remarks or not self.remarks.strip():
            raise UserError("Rejection reason is required.")

        if self.leave_id:
            # Used by both the manager-level Reject (waiting_manager) and
            # HR-level Reject (HR) (manager_approved) buttons on leave.request.
            if self.leave_id.state not in ('waiting_manager', 'manager_approved'):
                raise UserError("This leave request is no longer pending approval.")
            self.leave_id.write({'manager_remarks': self.remarks, 'state': 'rejected'})

        elif self.comp_leave_id:
            if self.comp_leave_id.state != 'waiting_manager':
                raise UserError("This request is no longer waiting for manager approval.")
            self.comp_leave_id.write({'manager_remarks': self.remarks, 'state': 'rejected'})

        return {'type': 'ir.actions.act_window_close'}
