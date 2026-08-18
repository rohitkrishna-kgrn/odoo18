from odoo import models, fields


class AccountInvoiceFollowupLog(models.Model):
    _name = 'account.invoice.followup.log'
    _description = 'Invoice Follow-up Log'
    _order = 'date desc, id desc'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='Follow-up Date',
        required=True,
        default=fields.Date.context_today,
    )
    method = fields.Selection(
        [
            ('email', 'Email'),
            ('call', 'Call'),
            ('whatsapp', 'WhatsApp'),
        ],
        string='Method',
        required=True,
    )
    response = fields.Text(string='Client Response')
    user_id = fields.Many2one(
        'res.users',
        string='Logged By',
        default=lambda self: self.env.user,
        required=True,
    )
