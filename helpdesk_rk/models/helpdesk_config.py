from odoo import models, fields, api

class HelpdeskConfig(models.Model):
    _name = 'helpdesk_rk.config'
    _inherit = 'res.config.settings'
    _description = 'Helpdesk Configuration'

    support_team_ids = fields.Many2many(
        'res.users',
        string='Support Team',
        domain="[('share','=',False)]",
        help="Users assigned to support team. They will receive notifications and see all tickets."
    )

    def get_values(self):
        res = super().get_values()
        param = self.env['ir.config_parameter'].sudo()
        team_ids = param.get_param('helpdesk_rk.support_team_ids', default='')
        res['support_team_ids'] = [(6, 0, list(map(int, team_ids.split(','))))] if team_ids else []
        return res

    def set_values(self):
        super().set_values()
        param = self.env['ir.config_parameter'].sudo()
        team_ids = self.support_team_ids.ids or []
        param.set_param('helpdesk_rk.support_team_ids', ','.join(map(str, team_ids)))
