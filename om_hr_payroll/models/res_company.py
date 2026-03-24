from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    secondary_logo = fields.Binary(string="Secondary Logo")
    secondary_logo_filename = fields.Char(string="Filename")
