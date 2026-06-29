from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ItFolder(models.Model):
    _name = 'it.folder'
    _description = 'IT Document Folder'
    _parent_name = 'parent_id'
    _parent_store = True
    _rec_name = 'complete_name'
    _order = 'complete_name'

    name = fields.Char('Folder Name', required=True)
    complete_name = fields.Char(
        'Complete Name',
        compute='_compute_complete_name',
        store=True,
        recursive=True,
    )
    parent_id = fields.Many2one(
        'it.folder',
        'Parent Folder',
        ondelete='cascade',
        index=True,
    )
    child_ids = fields.One2many('it.folder', 'parent_id', 'Sub Folders')
    parent_path = fields.Char(index=True, unaccent=False)
    description = fields.Text('Description')
    active = fields.Boolean('Active', default=True)
    document_ids = fields.One2many('it.document', 'folder_id', 'Documents')
    document_count = fields.Integer(
        compute='_compute_document_count',
        string='Document Count',
    )
    subfolder_count = fields.Integer(
        compute='_compute_subfolder_count',
        string='Sub-Folders',
    )

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for folder in self:
            if folder.parent_id:
                folder.complete_name = '%s / %s' % (
                    folder.parent_id.complete_name, folder.name
                )
            else:
                folder.complete_name = folder.name

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = self.env['it.document'].search_count(
                [('folder_id', '=', rec.id)]
            )

    def _compute_subfolder_count(self):
        for rec in self:
            rec.subfolder_count = len(rec.child_ids)

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if not self._check_recursion():
            raise ValidationError(
                'You cannot create a recursive folder structure.'
            )

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents — %s' % self.complete_name,
            'res_model': 'it.document',
            'view_mode': 'list,kanban,form',
            'domain': [('folder_id', '=', self.id)],
            'context': {'default_folder_id': self.id},
        }

    def action_create_document_here(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Document',
            'res_model': 'it.document',
            'view_mode': 'form',
            'context': {'default_folder_id': self.id},
            'target': 'current',
        }

    def action_add_existing_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Documents — %s' % self.name,
            'res_model': 'it.folder.add.document',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_folder_id': self.id},
        }

    def action_open_self(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.complete_name,
            'res_model': 'it.folder',
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref('it_dms.view_it_folder_explorer_form').id,
            'target': 'current',
        }
