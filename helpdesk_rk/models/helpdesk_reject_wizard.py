from odoo import fields, models
from odoo.exceptions import UserError


class HelpdeskTicketRejectWizard(models.TransientModel):
    _name = 'helpdesk_rk.ticket.reject.wizard'
    _description = 'Helpdesk Ticket Rejection Reason'

    ticket_id = fields.Many2one('helpdesk_rk.ticket', string='Ticket', required=True)
    reason = fields.Text(string='Reason / Remarks', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.ticket_id._check_user_in_support_team():
            raise UserError("Not authorized.")
        if not self.reason or not self.reason.strip():
            raise UserError("Please enter the reason or remarks before rejecting the ticket.")
        self.ticket_id.action_set_rejected(reason=self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
