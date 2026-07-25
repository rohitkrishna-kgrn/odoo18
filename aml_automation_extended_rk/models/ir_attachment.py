from odoo import models, fields


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    # Metadata used to reliably re-associate portal-uploaded director /
    # shareholder documents with their table row + doc slot across page
    # reloads and to support per-file removal (the descriptive `name`
    # field cannot be parsed back safely since it embeds free-text names).
    aml_line_type = fields.Selection([
        ('director', 'Director'),
        ('shareholder', 'Shareholder'),
    ], string='AML Line Type')
    aml_line_index = fields.Integer(string='AML Line Index')
    aml_doc_type = fields.Char(string='AML Doc Type')

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % self.id,
            'target': 'new',
        }

    def action_preview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=false' % self.id,
            'target': 'new',
        }
