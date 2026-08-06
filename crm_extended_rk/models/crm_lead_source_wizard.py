from odoo import fields, models


class CrmLeadSetSourceWizard(models.TransientModel):
    _name = 'crm.lead.set.source.wizard'
    _description = 'Set Lead Source Before Qualifying'

    lead_id = fields.Many2one('crm.lead', required=True, readonly=True)
    source_id = fields.Many2one('utm.source', string='Source', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.lead_id.source_id = self.source_id
        return {'type': 'ir.actions.act_window_close'}
