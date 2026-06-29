from odoo import models, fields


class ItDocumentVersion(models.Model):
    _name = 'it.document.version'
    _description = 'IT Document Version'
    _order = 'upload_date desc'
    _rec_name = 'version_number'

    document_id = fields.Many2one(
        'it.document',
        'Document',
        required=True,
        ondelete='cascade',
        index=True,
    )
    version_number = fields.Char('Version Number', required=True)
    uploaded_by = fields.Many2one(
        'res.users',
        'Uploaded By',
        default=lambda self: self.env.user,
    )
    upload_date = fields.Datetime('Upload Date', default=fields.Datetime.now)
    comments = fields.Text('Version Comments')
    attachment = fields.Binary('File', attachment=True)
    attachment_filename = fields.Char('Filename')
