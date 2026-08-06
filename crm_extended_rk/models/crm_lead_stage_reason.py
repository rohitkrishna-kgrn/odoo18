from odoo import fields, models


class CrmLeadStageReason(models.Model):
    _name = 'crm.lead.stage.reason'
    _description = 'Lead Qualification Stage Change Reason'
    _order = 'date desc, id desc'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade')
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    stage_id = fields.Many2one('crm.stage', string='Moved To', required=True)
    reason = fields.Text(required=True)
    user_id = fields.Many2one(
        'res.users', string='Logged By', default=lambda self: self.env.user)
