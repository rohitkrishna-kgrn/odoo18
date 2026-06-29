from odoo import models, fields


class ItFolderAddDocument(models.TransientModel):
    _name = 'it.folder.add.document'
    _description = 'Add Existing Documents to Folder'

    folder_id = fields.Many2one('it.folder', string='Folder', required=True, readonly=True)
    document_ids = fields.Many2many(
        'it.document',
        'it_folder_add_doc_wizard_rel',
        'wizard_id', 'document_id',
        string='Documents',
    )

    def action_confirm(self):
        self.document_ids.write({'folder_id': self.folder_id.id})
        return {'type': 'ir.actions.act_window_close'}
