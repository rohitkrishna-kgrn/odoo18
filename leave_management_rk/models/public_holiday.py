from odoo import models, fields, api

class PublicHoliday(models.Model):
    _name = 'public.holiday'
    _description = 'Public Holiday'

    name = fields.Char(string='Holiday Name')
    date = fields.Date(string='Date', required=True)
    month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'), ('04', 'April'),
        ('05', 'May'), ('06', 'June'), ('07', 'July'), ('08', 'August'),
        ('09', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], compute='_compute_month', store=True)

    @api.depends('date')
    def _compute_month(self):
        for record in self:
            record.month = record.date.strftime('%m') if record.date else False
