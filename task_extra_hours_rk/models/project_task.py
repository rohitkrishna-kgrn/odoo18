from odoo import models, fields, api

class ProjectTask(models.Model):
    _inherit = 'project.task'

    extra_hours_request_ids = fields.One2many('task.extra.hours', 'task_id', string="Extra Hours Requests")

    current_extra_hours_request_id = fields.Many2one(
        'task.extra.hours', string='Current Extra Hours Request',
        compute='_compute_current_extra_hours_request', store=False)

    @api.depends('extra_hours_request_ids')
    def _compute_current_extra_hours_request(self):
        for task in self:
            latest_request = task.extra_hours_request_ids.sorted('create_date', reverse=True)[:1]
            task.current_extra_hours_request_id = latest_request and latest_request[0] or False


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'
