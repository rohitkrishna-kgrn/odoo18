from odoo import models, fields


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    bank_iban = fields.Char(
        string='IBAN',
        related='bank_account_id.iban',
        readonly=False,
    )
    bank_swift_code = fields.Char(
        string='Swift Code',
        related='bank_account_id.swift_code',
        readonly=False,
    )
