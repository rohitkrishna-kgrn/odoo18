from odoo import models, fields, api


class ItDashboard(models.Model):
    _name = 'it.dashboard'
    _description = 'IT DMS Dashboard'

    name = fields.Char('Dashboard Name', default='IT DMS Dashboard')

    # Folder counters
    total_folders = fields.Integer(
        string='Top-Level Folders',
        compute='_compute_folder_stats',
    )
    total_subfolders = fields.Integer(
        string='Sub-Folders',
        compute='_compute_folder_stats',
    )
    folder_stat_ids = fields.Many2many(
        'it.folder',
        compute='_compute_folder_stats',
        string='Folders',
    )

    # Document status counters
    total_documents = fields.Integer(
        string='Total Documents',
        compute='_compute_document_stats',
    )
    active_documents = fields.Integer(
        string='Active',
        compute='_compute_document_stats',
    )
    draft_documents = fields.Integer(
        string='Draft',
        compute='_compute_document_stats',
    )
    archived_documents = fields.Integer(
        string='Archived',
        compute='_compute_document_stats',
    )

    recent_document_ids = fields.Many2many(
        'it.document',
        compute='_compute_recent_documents',
        string='Recently Uploaded',
    )

    @api.depends()
    def _compute_folder_stats(self):
        Folder = self.env['it.folder']
        top_folders = Folder.search([('parent_id', '=', False)], order='name')
        for rec in self:
            rec.total_folders = len(top_folders)
            rec.total_subfolders = Folder.search_count([('parent_id', '!=', False)])
            rec.folder_stat_ids = top_folders

    @api.depends()
    def _compute_document_stats(self):
        Doc = self.env['it.document']
        for rec in self:
            rec.total_documents = Doc.search_count([])
            rec.active_documents = Doc.search_count([('status', '=', 'active')])
            rec.draft_documents = Doc.search_count([('status', '=', 'draft')])
            rec.archived_documents = Doc.search_count([('status', '=', 'archived')])

    @api.depends()
    def _compute_recent_documents(self):
        recent = self.env['it.document'].search(
            [], order='create_date desc', limit=10
        )
        for rec in self:
            rec.recent_document_ids = recent

    # ── Quick-navigation actions ────────────────────────────────────────────

    def action_open_folders(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Folders',
            'res_model': 'it.folder',
            'view_mode': 'kanban,list,form',
            'domain': [('parent_id', '=', False)],
        }

    def action_open_all_documents(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'All Documents',
            'res_model': 'it.document',
            'view_mode': 'list,kanban,form',
        }

    def action_open_active_documents(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Active Documents',
            'res_model': 'it.document',
            'view_mode': 'list,kanban,form',
            'domain': [('status', '=', 'active')],
        }

    def action_open_draft_documents(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Draft Documents',
            'res_model': 'it.document',
            'view_mode': 'list,kanban,form',
            'domain': [('status', '=', 'draft')],
        }
