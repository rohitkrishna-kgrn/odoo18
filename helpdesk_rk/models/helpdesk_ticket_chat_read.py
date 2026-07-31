from odoo import fields, models


class HelpdeskTicketChatRead(models.Model):
    _name = 'helpdesk_rk.ticket.chat.read'
    _description = 'Helpdesk Ticket Chat Read State'

    ticket_id = fields.Many2one('helpdesk_rk.ticket', string='Ticket', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade', index=True)
    last_read_date = fields.Datetime(string='Last Read On', required=True)

    _sql_constraints = [
        ('ticket_user_uniq', 'unique(ticket_id, user_id)', 'A read state already exists for this ticket and user.'),
    ]
