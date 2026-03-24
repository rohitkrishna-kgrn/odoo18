from odoo import models, fields, api
from odoo.exceptions import UserError

class TaskEndWizard(models.TransientModel):
    _name = 'task.end.wizard'
    _description = 'Wizard to end task and submit timesheet'

    task_id = fields.Many2one('project.task', string="Task", required=True)
    timer_id = fields.Many2one('task.timer', string="Timer", required=True)
    description = fields.Text(string="Description", required=True)
    start_time = fields.Datetime(string="Start Time", required=True)
    end_time = fields.Datetime(string="End Time", required=True)

    def action_submit_timesheet(self):
        self.ensure_one()

        start_dt = fields.Datetime.to_datetime(self.start_time)
        end_dt = fields.Datetime.to_datetime(self.end_time)

        if end_dt <= start_dt:
            raise UserError("End Time must be after Start Time.")

        duration = (end_dt - start_dt).total_seconds() / 3600.0

        # Update timer record to mark it finished
        self.timer_id.write({
            'end_time': self.end_time,
            'is_active': False,
        })

        # Create timesheet line
        self.env['account.analytic.line'].create({
            'name': self.description or f'Work on task {self.task_id.name}',
            'project_id': self.task_id.project_id.id,
            'task_id': self.task_id.id,
            'date': fields.Date.to_date(self.end_time),
            'unit_amount': duration,
            'user_id': self.env.user.id,
            # 'account_id': self.task_id.analytic_account_id.id,
        })

        return {'type': 'ir.actions.act_window_close'}
