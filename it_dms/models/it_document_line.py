from odoo import models, fields, api
from odoo.exceptions import UserError


class ItDocumentLine(models.Model):
    _name = 'it.document.line'
    _description = 'IT Document File'
    _order = 'sequence, id'

    document_id = fields.Many2one(
        'it.document', 'Document',
        required=True, ondelete='cascade', index=True,
    )
    sequence = fields.Integer('Seq.', default=10)
    filename = fields.Char('File Name')
    description = fields.Char('Description')
    file = fields.Binary('File', attachment=True)
    uploaded_by = fields.Many2one(
        'res.users',
        'Uploaded By',
        default=lambda self: self.env.user,
        readonly=True,
    )
    uploaded_date = fields.Datetime(
        'Uploaded Date',
        default=fields.Datetime.now,
        readonly=True,
    )

    def action_download_file(self):
        self.ensure_one()
        if not self.file:
            raise UserError('No file is attached to this line.')
        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/web/content?model=it.document.line&id=%s'
                '&field=file&filename_field=filename&download=true'
            ) % self.id,
            'target': 'self',
        }
