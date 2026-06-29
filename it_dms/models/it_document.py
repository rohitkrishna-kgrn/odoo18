from odoo import models, fields, api
from odoo.exceptions import UserError


class ItDocument(models.Model):
    _name = 'it.document'
    _description = 'IT Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    _rec_name = 'name'

    name = fields.Char('Document Name', required=True, tracking=True)
    document_code = fields.Char(
        'Document Code',
        readonly=True,
        copy=False,
        default='New',
        index=True,
    )
    description = fields.Text('Description')
    category_id = fields.Many2one(
        'it.category', 'Category', tracking=True, index=True
    )
    folder_id = fields.Many2one(
        'it.folder', 'Folder', tracking=True, index=True
    )
    tag_ids = fields.Many2many('it.tag', string='Tags')
    owner_id = fields.Many2one(
        'res.users',
        'Owner',
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
    )
    version = fields.Char('Version', default='1.0', tracking=True)

    attachment_file = fields.Binary('File', attachment=True)
    attachment_filename = fields.Char('Filename')

    status = fields.Selection(
        [
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('archived', 'Archived'),
        ],
        string='Status',
        default='draft',
        tracking=True,
        index=True,
    )

    document_type = fields.Selection(
        [
            ('sop', 'SOP'),
            ('technical', 'Technical Documentation'),
            ('network_diagram', 'Network Diagram'),
            ('server_doc', 'Server Documentation'),
            ('install_guide', 'Installation Guide'),
            ('software_license', 'Software License'),
            ('user_manual', 'User Manual'),
            ('project_doc', 'Project Documentation'),
            ('backup', 'Backup Procedure'),
            ('security', 'Security Policy'),
            ('others', 'Others'),
        ],
        string='Document Type',
        default='others',
        tracking=True,
        index=True,
    )

    notes = fields.Html('Notes')

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'it_document_attachment_rel',
        'document_id',
        'attachment_id',
        string='Files',
    )

    line_ids = fields.One2many('it.document.line', 'document_id', 'Description Lines')

    version_ids = fields.One2many(
        'it.document.version', 'document_id', 'Version History'
    )
    version_count = fields.Integer(
        compute='_compute_version_count',
        string='Versions',
    )
    file_count = fields.Integer(
        compute='_compute_file_count',
        string='File Count',
    )
    user_id = fields.Many2one(
        related='owner_id',
        string='User',
        store=False,
    )
    file_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_file_ids',
        string='File List',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('document_code', 'New') == 'New':
                vals['document_code'] = (
                    self.env['ir.sequence'].next_by_code('it.document') or 'New'
                )
        return super().create(vals_list)

    def _compute_version_count(self):
        for rec in self:
            rec.version_count = len(rec.version_ids)

    def _compute_file_count(self):
        IrAttachment = self.env['ir.attachment']
        for rec in self:
            rec.file_count = IrAttachment.search_count([
                ('res_model', '=', 'it.document'),
                ('res_id', '=', rec.id),
            ])

    def _compute_file_ids(self):
        IrAttachment = self.env['ir.attachment']
        for rec in self:
            rec.file_ids = IrAttachment.search([
                ('res_model', '=', 'it.document'),
                ('res_id', '=', rec.id),
            ])

    def action_activate(self):
        self.write({'status': 'active'})

    def action_archive_doc(self):
        self.write({'status': 'archived'})

    def action_set_draft(self):
        self.write({'status': 'draft'})

    def action_view_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Version History',
            'res_model': 'it.document.version',
            'view_mode': 'list,form',
            'domain': [('document_id', '=', self.id)],
            'context': {'default_document_id': self.id},
        }

    def action_upload_version(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Upload New Version',
            'res_model': 'it.document.version',
            'view_mode': 'form',
            'context': {
                'default_document_id': self.id,
                'default_version_number': self._get_next_version(),
                'default_uploaded_by': self.env.uid,
            },
            'target': 'new',
        }

    def _get_next_version(self):
        try:
            current = float(self.version or '1.0')
            return str(round(current + 0.1, 1))
        except (ValueError, TypeError):
            return '1.1'

    def copy(self, default=None):
        default = dict(default or {})
        default.update({
            'document_code': 'New',
            'name': '%s (Copy)' % self.name,
            'status': 'draft',
            'version': '1.0',
        })
        return super().copy(default)

    def action_download_file(self):
        self.ensure_one()
        if not self.attachment_file:
            raise UserError('No file is attached to this document.')
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content?model=it.document&id=%s'
                '&field=attachment_file&filename_field=attachment_filename&download=true'
            ) % self.id,
            'target': 'self',
        }

    def action_print_document(self):
        self.ensure_one()
        return self.env.ref('it_dms.action_report_it_document').report_action(self)

    def unlink(self):
        if self.ids:
            self.env.cr.execute(
                "DELETE FROM it_folder_add_doc_wizard_rel WHERE document_id = ANY(%s)",
                (list(self.ids),)
            )
        return super().unlink()

    def action_remove_from_folder(self):
        self.write({'folder_id': False})
