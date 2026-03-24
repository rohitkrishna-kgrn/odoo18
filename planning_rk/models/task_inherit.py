from odoo import models, fields, api

class ProjectTask(models.Model):
    _inherit = 'project.task'

    planning_stage = fields.Selection([
        ('new', 'New'),
        ('today', 'Today'),
        ('this_week', 'This Week'),
        ('this_month', 'This Month'),
        ('later', 'Later'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Planning Stage')

    planning_id = fields.Many2one('planning.rk', string='Planning Record', readonly=True)

    def write(self, vals):
        res = super().write(vals)
        if 'planning_stage' in vals:
            for task in self:
                if task.planning_id:
                    stage = self.env['planning.stage'].search([('selection_key', '=', vals['planning_stage'])], limit=1)
                    if stage:
                        task.planning_id.stage_id = stage.id
        return res
