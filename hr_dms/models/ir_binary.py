from odoo import models


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _get_stream_from(self, record, field_name='raw', *args, **kwargs):
        # /web/content and /web/image on a document file: the record rules already decided who may
        # read the document, this adds the category's "Employee can download" flag
        if record._name == 'ir.attachment':
            record._hr_dms_guard()._check_download(detail=record.sudo().name)
        return super()._get_stream_from(record, field_name, *args, **kwargs)
