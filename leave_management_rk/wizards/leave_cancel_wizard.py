from markupsafe import Markup

from odoo import models, fields
from odoo.exceptions import UserError


class LeaveCancelWizard(models.TransientModel):
    _name = 'leave.cancel.wizard'
    _description = 'Cancel Approved Leave Wizard'

    leave_id = fields.Many2one('leave.request', string='Leave Request', required=True)
    reason = fields.Text(string='Cancellation Reason', required=True)

    def action_confirm_cancel(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError("Please provide a reason for cancelling this leave.")

        leave = self.leave_id
        leave.action_cancel_approved()
        # Markup's % escapes each substituted value (name, reason), so the
        # user-typed reason can never inject stray HTML into the chatter -
        # only the <p> skeleton itself renders. A plain str body would be
        # escaped whole by message_post(), showing literal <p> tags instead.
        leave.message_post(
            body=Markup("<p>Leave request cancelled by %s.</p><p>Reason: %s</p>") % (
                self.env.user.name, self.reason)
        )
        return {'type': 'ir.actions.act_window_close'}
