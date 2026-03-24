from odoo import models, fields

class DashboardConfigRK(models.Model):
    _name = 'dashboard.config.rk'
    _description = 'Dashboard Config RK'

    name = fields.Char(string='Person Name', required=True)
    percentage = fields.Float(string='Percentage', required=True)
