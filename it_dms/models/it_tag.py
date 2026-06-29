from odoo import models, fields


class ItTag(models.Model):
    _name = 'it.tag'
    _description = 'IT Document Tag'
    _order = 'name'

    name = fields.Char('Tag Name', required=True, translate=True)
    color = fields.Integer('Color Index', default=0)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Tag name must be unique.'),
    ]
