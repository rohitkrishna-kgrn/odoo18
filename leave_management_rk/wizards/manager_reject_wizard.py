from odoo import models, fields
from odoo.exceptions import UserError


class LeaveManagerRejectWizard(models.TransientModel):
    _name = 'leave.manager.reject.wizard'
    _description = 'Manager Leave Rejection Wizard'

    leave_id = fields.Many2one('leave.request', string='Leave Request')
    comp_leave_id = fields.Many2one('leave.comp.request', string='Comp Leave Request')
    remarks = fields.Text(string='Rejection Remarks', required=True)

    def action_reject(self):
        self.ensure_one()
        if not self.remarks or not self.remarks.strip():
            raise UserError("Please provide rejection remarks.")

        if self.leave_id:
            if self.leave_id.state != 'waiting_manager':
                raise UserError("This leave request is no longer waiting for manager approval.")
            self.leave_id.write({'manager_remarks': self.remarks, 'state': 'rejected'})

        elif self.comp_leave_id:
            if self.comp_leave_id.state != 'waiting_manager':
                raise UserError("This request is no longer waiting for manager approval.")
            self.comp_leave_id.write({'manager_remarks': self.remarks, 'state': 'rejected'})

        return {'type': 'ir.actions.act_window_close'}
