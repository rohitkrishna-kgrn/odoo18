from odoo import fields, models

class HelpdeskStage(models.Model):
    _name = 'helpdesk_rk.stage'
    _description = 'Helpdesk Stage'
    _order = 'sequence'

    name = fields.Char('Stage Name', required=True)
    sequence = fields.Integer('Sequence', default=10)
