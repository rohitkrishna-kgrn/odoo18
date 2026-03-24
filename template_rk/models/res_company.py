from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    invoice_color = fields.Char(string="Invoice Color", default="#000000")
    invoice_bank_ids = fields.Many2many(
        'res.partner.bank',
        string="Bank Accounts for Invoices",
        domain="[('partner_id', '=', partner_id)]"
    )


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    iban = fields.Char(string='IBAN')