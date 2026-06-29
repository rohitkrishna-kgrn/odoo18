import uuid
from odoo import models, fields


class ContactFormToken(models.Model):
    _name = 'contact.form.token'
    _description = 'Customer Information Form Token'
    _rec_name = 'token'

    token = fields.Char(
        string='Token',
        required=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
        index=True,
        readonly=True,
    )
    partner_id = fields.Many2one('res.partner', string='Contact', ondelete='set null')
    base_url = fields.Char(string='Base URL')
    expiry_date = fields.Datetime(string='Expiry Date', readonly=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
    ], string='Status', default='pending', required=True, readonly=True)
    submitted_date = fields.Datetime(string='Submitted On', readonly=True)
