# models/res_users.py
from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    sales_team = fields.Boolean(string="Sales Team")
