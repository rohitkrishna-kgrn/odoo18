from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    approver_user_id = fields.Many2one('res.users', string="Quotation Approver User")
