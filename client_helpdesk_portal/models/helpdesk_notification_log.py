from odoo import fields, models


class ClientHelpdeskNotificationLog(models.Model):
    _name = 'client.helpdesk.notification.log'
    _description = 'Helpdesk Notification Log'
    _order = 'date_time desc, id desc'
    _rec_name = 'subject'

    ticket_id = fields.Many2one(
        'client.helpdesk.ticket', string='Ticket', ondelete='cascade',
        index=True, readonly=True,
    )
    ticket_number = fields.Char(
        related='ticket_id.ticket_number', store=True, readonly=True,
        string='Ticket Number',
    )
    client_name = fields.Char(
        related='ticket_id.client_name', store=True, readonly=True,
        string='Client',
    )
    event_type = fields.Selection([
        ('email', 'Email Sent'),
        ('portal_view', 'Client Portal View'),
        ('reopen', 'Ticket Reopened'),
    ], required=True, readonly=True, string='Event Type', index=True)
    date_time = fields.Datetime(
        string='Date & Time', default=fields.Datetime.now,
        required=True, readonly=True, index=True,
    )
    email_from = fields.Char(string='From', readonly=True)
    email_to = fields.Char(string='To', readonly=True)
    recipient_label = fields.Char(
        string='Recipient', readonly=True,
        help='Client / Assigned User / Manager / Helpdesk Admin — inferred '
             'by matching the "To" address against the ticket at the time '
             'the email was sent.',
    )
    subject = fields.Char(readonly=True)
    mail_id = fields.Many2one(
        'mail.mail', string='Email Record', readonly=True, ondelete='set null',
        help='The underlying mail.mail record, if this row is an email '
             '(not a portal view) and it still exists.',
    )
