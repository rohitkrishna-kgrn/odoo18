from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MisRevenueRole(models.Model):
    _name = 'mis.revenue.role'
    _description = 'MIS Revenue Role'
    _order = 'multiplier desc, name'

    name       = fields.Char(string='Role Name',   required=True)
    multiplier = fields.Float(string='Multiplier', required=True, default=1.0, digits=(16, 2))
    active     = fields.Boolean(default=True)

    @api.constrains('multiplier')
    def _check_multiplier(self):
        for rec in self:
            if rec.multiplier <= 0:
                raise ValidationError("Multiplier must be greater than 0.")
