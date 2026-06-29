from odoo import models, fields, api

_IT_DMS_MODELS = frozenset({
    'it.document',
    'it.document.line',
    'it.document.version',
})


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    file_data = fields.Binary(related='datas', string='File Data', store=False)
    file_name = fields.Char(related='name', string='File Name', store=False)
    file_type = fields.Char(related='mimetype', string='File Type', store=False)
    file_url = fields.Char(related='url', string='File URL', store=False)

    @api.model_create_multi
    def create(self, vals_list):
        # The Helpdesk module installs a record rule on ir.attachment that blocks
        # attachment creation for users who are not Helpdesk Managers.
        # For IT DMS attachments we bypass that restriction via sudo() since access
        # is already enforced at the it.document / it.document.line level.
        if any(v.get('res_model') in _IT_DMS_MODELS for v in vals_list):
            return super(IrAttachment, self.sudo()).create(vals_list)
        return super().create(vals_list)
