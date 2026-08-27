from odoo import models


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def write(self, vals):
        # A task can only reach 'Done' once its project has confirmed
        # invoicing; this blocks the transition regardless of how it's
        # triggered (Approve button, bulk close, kanban drag, direct edit).
        becoming_done = False
        if vals.get('stage_id'):
            becoming_done = self.env['project.task.type'].browse(vals['stage_id']).name == 'Done'
        elif vals.get('state_additional') == 'completed':
            becoming_done = True
        if becoming_done:
            for task in self:
                if task.stage_id.name != 'Done' and task.project_id:
                    task.project_id._check_closure_invoice_confirmed()

        return super().write(vals)
