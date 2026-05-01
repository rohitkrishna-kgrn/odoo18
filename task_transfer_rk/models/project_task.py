from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Re-declare only to enable tracking; all other attributes remain from project_extended_rk
    team_member_ids = fields.Many2many('res.users', tracking=True)
