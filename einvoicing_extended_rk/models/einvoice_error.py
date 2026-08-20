# -*- coding: utf-8 -*-
from odoo import fields, models


class EinvoiceError(models.Model):
    """One PINT-AE validation error returned inside results[].errors[].

    ``field`` and ``fix`` are written by the platform to be shown to a finance
    user, so they are what the invoice form surfaces.
    """
    _name = 'einvoice.error'
    _description = 'eInvoice Validation Error'
    _order = 'move_id, id'

    move_id = fields.Many2one(
        'account.move', string='Invoice', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', related='move_id.company_id', store=True)
    rule = fields.Char(string='Rule', help='The PINT-AE rule id, e.g. IBR-001-AE.')
    field_name = fields.Char(string='Field')
    message = fields.Char(string='Message')
    fix = fields.Char(string='How to Fix')
    date = fields.Datetime(string='Reported On', default=fields.Datetime.now)
