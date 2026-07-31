import base64
from urllib.parse import quote

from odoo import models, fields, api, _

# Office formats have no native browser renderer, so a direct link always
# downloads instead of previewing. Route these through an external embedded
# viewer instead of the raw file URL.
OFFICE_VIEWER_FILE_TYPES = {'DOC', 'DOCX', 'XLS', 'XLSX', 'PPT', 'PPTX', 'RTF', 'ODT', 'ODS', 'ODP'}


class ITDocumentCategory(models.Model):
    _name = 'it.document.category'
    _description = 'IT Document Category'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer(string='Color Index')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A document category with this name already exists.'),
    ]


class ITDocumentTag(models.Model):
    _name = 'it.document.tag'
    _description = 'IT Document Tag'
    _order = 'name'

    name = fields.Char(required=True)
    color = fields.Integer(string='Color Index')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'A document tag with this name already exists.'),
    ]


class ITDocumentFolder(models.Model):
    _name = 'it.document.folder'
    _description = 'IT Document Folder'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Folder Name', required=True, tracking=True)
    description = fields.Text(string='Description')
    doc_type = fields.Selection([
        ('development', 'Development Documents'),
        ('test', 'Test Documents'),
        ('manual', 'User Manuals'),
    ], string='Document Menu', required=True, default='development', tracking=True, index=True)
    document_ids = fields.One2many('it.document.file', 'folder_id', string='Documents')
    file_count = fields.Integer(string='Total Files', compute='_compute_file_count', store=True)
    total_size = fields.Integer(string='Total Size', compute='_compute_file_count', store=True)
    total_size_display = fields.Char(string='Storage Used', compute='_compute_total_size_display')
    active = fields.Boolean(default=True)
    color = fields.Integer(string='Color')

    @api.depends('document_ids.active', 'document_ids.file_size')
    def _compute_file_count(self):
        groups = self.env['it.document.file']._read_group(
            [('folder_id', 'in', self.ids)],
            groupby=['folder_id'],
            aggregates=['__count', 'file_size:sum'],
        )
        stats = {folder: (count, size) for folder, count, size in groups}
        for folder in self:
            count, size = stats.get(folder, (0, 0))
            folder.file_count = count
            folder.total_size = size

    @api.depends('total_size')
    def _compute_total_size_display(self):
        for folder in self:
            folder.total_size_display = self.env['it.document.file']._format_file_size(folder.total_size)

    def action_download_all(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/it_document/folder/{self.id}/zip',
            'target': 'self',
        }

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Documents - %s', self.name),
            'res_model': 'it.document.file',
            'view_mode': 'kanban,list,form',
            'domain': [('folder_id', '=', self.id)],
            'context': {'default_folder_id': self.id, 'default_doc_type': self.doc_type},
        }

    def action_view_latest_documents(self):
        self.ensure_one()
        action = self.action_view_documents()
        action['name'] = _('Latest Documents - %s', self.name)
        list_view = self.env.ref('assets_rk.view_it_document_file_list_latest', raise_if_not_found=False)
        form_view = self.env.ref('assets_rk.view_it_document_file_form', raise_if_not_found=False)
        if list_view:
            action['views'] = [(list_view.id, 'list'), (form_view.id if form_view else False, 'form')]
            action['view_mode'] = 'list,form'
        return action

    def action_view_folder_statistics(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Folder Statistics - %s', self.name),
            'res_model': 'it.document.file',
            'view_mode': 'pivot,graph',
            'domain': [('folder_id', '=', self.id)],
        }


class ITDocumentFile(models.Model):
    _name = 'it.document.file'
    _description = 'IT Document File'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Document Name', required=True, tracking=True)
    folder_id = fields.Many2one('it.document.folder', string='Folder', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    doc_type = fields.Selection(related='folder_id.doc_type', string='Document Menu', store=True, index=True)
    category_id = fields.Many2one('it.document.category', string='Document Category', index=True, tracking=True)
    color = fields.Integer(string='Color', related='category_id.color', store=True, readonly=True)
    description = fields.Text(string='Description')
    version = fields.Integer(string='Version', default=1, readonly=True, copy=False)
    datas = fields.Binary(string='Uploaded File', attachment=True, required=True)
    file_name = fields.Char(string='File Name')
    file_type = fields.Char(string='File Type', compute='_compute_file_info', store=True)
    file_size = fields.Integer(string='File Size', compute='_compute_file_info', store=True)
    file_size_display = fields.Char(string='Size', compute='_compute_file_size_display')
    is_pdf = fields.Boolean(string='Is PDF', compute='_compute_file_info', store=True)
    uploaded_by = fields.Many2one('res.users', string='Uploaded By',
                                   default=lambda self: self.env.user, index=True, tracking=True)
    upload_date = fields.Datetime(string='Upload Date', default=fields.Datetime.now, tracking=True)
    tag_ids = fields.Many2many('it.document.tag', string='Tags')
    active = fields.Boolean(default=True)
    version_history_ids = fields.One2many('it.document.file.version', 'document_id', string='Version History')
    favorite_user_ids = fields.Many2many('res.users', 'it_document_file_favorite_rel', 'file_id', 'user_id',
                                          string='Favorited By')
    is_favorite = fields.Boolean(string='Favorite', compute='_compute_is_favorite',
                                  inverse='_inverse_is_favorite', search='_search_is_favorite')
    download_count = fields.Integer(string='Downloads', default=0, copy=False, readonly=True)

    def _compute_is_favorite(self):
        for rec in self:
            rec.is_favorite = self.env.user in rec.favorite_user_ids

    def _inverse_is_favorite(self):
        favorited = unfavorited = self.env['it.document.file']
        for rec in self:
            if self.env.user in rec.favorite_user_ids:
                unfavorited |= rec
            else:
                favorited |= rec
        favorited.write({'favorite_user_ids': [(4, self.env.uid)]})
        unfavorited.write({'favorite_user_ids': [(3, self.env.uid)]})

    def _search_is_favorite(self, operator, value):
        favorite = (operator == '=' and value) or (operator == '!=' and not value)
        domain_operator = 'in' if favorite else 'not in'
        return [('favorite_user_ids', domain_operator, self.env.user.id)]

    @api.depends('file_name', 'datas')
    def _compute_file_info(self):
        for rec in self:
            if rec.file_name and '.' in rec.file_name:
                rec.file_type = rec.file_name.rsplit('.', 1)[-1].upper()
            else:
                rec.file_type = False
            # bin_size may be set in the ambient context (e.g. web_save re-reads
            # with bin_size=True), which replaces datas with a size string instead
            # of real base64 content, breaking b64decode. Force real content here.
            datas = rec.with_context(bin_size=False).datas
            rec.file_size = len(base64.b64decode(datas)) if datas else 0
            rec.is_pdf = rec.file_type == 'PDF'

    @api.depends('file_size')
    def _compute_file_size_display(self):
        for rec in self:
            rec.file_size_display = rec._format_file_size(rec.file_size)

    @api.model
    def _format_file_size(self, size):
        if not size:
            return '0 B'
        value = float(size)
        for unit in ('B', 'KB', 'MB', 'GB'):
            if value < 1024.0:
                return f'{int(value)} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
            value /= 1024.0
        return f'{value:.1f} TB'

    def action_download(self):
        self.ensure_one()
        self.download_count += 1
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/datas?download=true',
            'target': 'self',
        }

    def _get_datas_attachment(self):
        self.ensure_one()
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('res_field', '=', 'datas'),
        ], limit=1)

    def action_view_file(self):
        self.ensure_one()
        content_url = f'/web/content/{self._name}/{self.id}/datas'

        if (self.file_type or '').upper() in OFFICE_VIEWER_FILE_TYPES:
            attachment = self._get_datas_attachment()
            if attachment:
                token = attachment.generate_access_token()[0]
                file_url = f'{self.get_base_url()}{content_url}?access_token={token}'
                return {
                    'type': 'ir.actions.act_url',
                    'url': f'https://view.officeapps.live.com/op/view.aspx?src={quote(file_url, safe="")}',
                    'target': 'new',
                }

        return {
            'type': 'ir.actions.act_url',
            'url': content_url,
            'target': 'new',
        }

    def action_open_replace_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Replace File'),
            'res_model': 'it.document.replace.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_document_id': self.id, 'default_file_name': self.file_name},
        }


class ITDocumentFileVersion(models.Model):
    _name = 'it.document.file.version'
    _description = 'IT Document Version History'
    _order = 'create_date desc'

    document_id = fields.Many2one('it.document.file', required=True, ondelete='cascade', index=True)
    version = fields.Integer(string='Version')
    datas = fields.Binary(string='File', attachment=True)
    file_name = fields.Char(string='File Name')
    file_size = fields.Integer(string='File Size')
    uploaded_by = fields.Many2one('res.users', string='Uploaded By')
    upload_date = fields.Datetime(string='Upload Date')

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self._name}/{self.id}/datas?download=true',
            'target': 'self',
        }


class ITDocumentReplaceWizard(models.TransientModel):
    _name = 'it.document.replace.wizard'
    _description = 'Replace IT Document File'

    document_id = fields.Many2one('it.document.file', required=True, readonly=True)
    datas = fields.Binary(string='New File', required=True)
    file_name = fields.Char(string='File Name', required=True)

    def action_confirm(self):
        self.ensure_one()
        self = self.with_context(bin_size=False)
        doc = self.document_id.with_context(bin_size=False)
        self.env['it.document.file.version'].create({
            'document_id': doc.id,
            'version': doc.version,
            'datas': doc.datas,
            'file_name': doc.file_name,
            'file_size': doc.file_size,
            'uploaded_by': doc.uploaded_by.id,
            'upload_date': doc.upload_date,
        })
        doc.write({
            'datas': self.datas,
            'file_name': self.file_name,
            'version': doc.version + 1,
            'uploaded_by': self.env.user.id,
            'upload_date': fields.Datetime.now(),
        })
        return {'type': 'ir.actions.act_window_close'}
