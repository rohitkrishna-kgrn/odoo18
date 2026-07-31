from odoo import fields, models
from odoo.exceptions import UserError


class HelpdeskTicketDeadlineWizard(models.TransientModel):
    _name = 'helpdesk_rk.ticket.deadline.wizard'
    _description = 'Helpdesk Ticket Overdue Deadline Change Reason'

    ticket_id = fields.Many2one('helpdesk_rk.ticket', string='Ticket', required=True)
    old_deadline_date = fields.Date(string='Current Deadline', related='ticket_id.deadline_date', readonly=True)
    new_deadline_date = fields.Date(string='New Deadline Date', required=True)
    reason = fields.Text(string='Reason / Remarks', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.ticket_id._check_user_in_support_team():
            raise UserError("Not authorized.")
        if not self.reason or not self.reason.strip():
            raise UserError("Please enter the reason for changing the overdue deadline.")
        self.ticket_id.action_change_overdue_deadline(self.new_deadline_date, self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
