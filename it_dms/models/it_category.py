from odoo import models, fields


class ItCategory(models.Model):
    _name = 'it.category'
    _description = 'IT Document Category'
    _order = 'name'

    name = fields.Char('Category Name', required=True, translate=True)
    description = fields.Text('Description')
    color = fields.Integer('Color Index', default=0)
    document_count = fields.Integer(
        compute='_compute_document_count',
        string='Documents',
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Category name must be unique.'),
    ]

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = self.env['it.document'].search_count(
                [('category_id', '=', rec.id)]
            )

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents - %s' % self.name,
            'res_model': 'it.document',
            'view_mode': 'list,form,kanban',
            'domain': [('category_id', '=', self.id)],
        }
