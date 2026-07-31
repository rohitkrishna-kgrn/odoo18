from odoo import api, fields, models
from .helpdesk_ticket import to_gst


class ClientHelpdeskReasonLine(models.Model):
    _name = 'client.helpdesk.reason.line'
    _description = 'Helpdesk Ticket Reason / Action History'
    _order = 'date_time desc, id desc'

    ticket_id = fields.Many2one(
        'client.helpdesk.ticket', required=True, ondelete='cascade', index=True,
    )
    action_type = fields.Selection([
        ('resume', 'Resume'),
        ('resolve', 'Resolved'),
        ('close', 'Closed'),
        ('reopen', 'Reopened'),
    ], required=True, index=True)
    date_time = fields.Datetime(default=fields.Datetime.now, required=True)
    reason = fields.Text(required=True)
    date_gst = fields.Char('Date', compute='_compute_gst_display')
    time_gst = fields.Char('Time', compute='_compute_gst_display')

    @api.depends('date_time')
    def _compute_gst_display(self):
        for rec in self:
            dt = to_gst(rec.date_time)
            rec.date_gst = dt.strftime('%d %b %Y') if dt else ''
            rec.time_gst = f'{dt.strftime("%H:%M")} GST' if dt else ''
