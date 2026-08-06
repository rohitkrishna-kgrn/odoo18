from odoo import fields, models


class CrmLeadSetReasonWizard(models.TransientModel):
    _name = 'crm.lead.set.reason.wizard'
    _description = 'Capture a Reason When Changing Lead Qualification Stage'

    lead_id = fields.Many2one('crm.lead', required=True, readonly=True)
    target_stage_id = fields.Many2one('crm.stage', required=True, readonly=True)
    reason = fields.Text(required=True)

    def action_confirm(self):
        self.ensure_one()
        self.env['crm.lead.stage.reason'].create({
            'lead_id': self.lead_id.id,
            'stage_id': self.target_stage_id.id,
            'reason': self.reason,
        })
        self.lead_id.write({'stage_id': self.target_stage_id.id, 'active': True})
        return {'type': 'ir.actions.act_window_close'}
