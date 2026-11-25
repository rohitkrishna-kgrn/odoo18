from odoo import fields, models


class ResBank(models.Model):
    _inherit = 'res.bank'

    ifsc_prefix = fields.Char(string='IFSC Bank Code', size=4,
                              help="India: the first 4 letters of every IFSC of this bank (e.g. HDFC, SBIN). "
                                   "Payroll checks the employee's IFSC against it.")
