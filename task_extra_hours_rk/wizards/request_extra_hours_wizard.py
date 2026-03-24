from odoo import models, fields, api
from odoo.exceptions import ValidationError

class RequestExtraHoursWizard(models.TransientModel):
    _name = 'request.extra.hours.wizard'
    _description = 'Request Extra Hours Wizard'

    task_id = fields.Many2one('project.task', string="Task", required=True)
    extra_hours = fields.Float(string="Extra Hours", required=True)
    reason = fields.Text(string="Reason", required=True)

    def action_submit(self):
        if self.extra_hours <= 0:
            raise ValidationError("Extra hours must be greater than 0.")
        self.env['task.extra.hours'].create({
            'task_id': self.task_id.id,
            'extra_hours': self.extra_hours,
            'reason': self.reason,
        })
        return {'type': 'ir.actions.act_window_close'}
