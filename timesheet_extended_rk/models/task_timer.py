from odoo import models, fields, api
from odoo.exceptions import UserError

class TaskTimer(models.Model):
    _name = 'task.timer'
    _description = 'Task Timer per user'

    user_id = fields.Many2one('res.users', required=True, default=lambda self: self.env.user)
    task_id = fields.Many2one('project.task', required=True)
    project_id = fields.Many2one('project.project', related='task_id.project_id', store=True)
    start_time = fields.Datetime(required=True, default=fields.Datetime.now)
    end_time = fields.Datetime()
    is_active = fields.Boolean(default=True)

class ProjectTask(models.Model):
    _inherit = 'project.task'

    user_active_timer = fields.Boolean(compute='_compute_user_active_timer')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')

    @api.depends()
    def _compute_user_active_timer(self):
        for task in self:
            # logic to check if current user has an active timer for this task
            active_timer = self.env['task.timer'].search([
                ('task_id', '=', task.id),
                ('user_id', '=', self.env.user.id),
                ('end_time', '=', False),
            ], limit=1)
            task.user_active_timer = bool(active_timer)

    def action_start_task(self):
        self.ensure_one()
        
        # 1. Check if task stage is 'In Progress'
        in_progress_stage = self.env['project.task.type'].sudo().search([('name', '=', 'In Progress')], limit=1)
        if self.stage_id != in_progress_stage:
            raise UserError("You can only start a task which is in 'In Progress' stage.")
        
        # 2. Check if user is currently checked in (attendance)
        attendance = self.env['hr.attendance'].sudo().search([
            ('employee_id.user_id', '=', self.env.user.id),
            ('check_out', '=', False)
        ], limit=1)
        if not attendance:
            raise UserError("You need to be checked in (attendance) before starting a task.")
        
        # 3. Check if user is assigned in team_member_ids on this task
        if self.env.user not in self.team_member_ids:
            raise UserError("You are not assigned to this task's team members.")
        
        # Existing: Check if user already has active timer for this task
        existing = self.env['task.timer'].search([
            ('task_id', '=', self.id),
            ('user_id', '=', self.env.user.id),
            ('is_active', '=', True)
        ])
        if not existing:
            self.env['task.timer'].create({
                'task_id': self.id,
                'user_id': self.env.user.id,
                'start_time': fields.Datetime.now(),
                'is_active': True,
            })
        return True

    def action_end_task(self):
        self.ensure_one()
        timer = self.env['task.timer'].search([
            ('task_id', '=', self.id),
            ('user_id', '=', self.env.user.id),
            ('is_active', '=', True)
        ], limit=1)
        if timer:
            return {
                'name': 'End Task Description',
                'type': 'ir.actions.act_window',
                'res_model': 'task.end.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_task_id': self.id,
                    'default_timer_id': timer.id,
                    'default_start_time': timer.start_time,
                    'default_end_time': fields.Datetime.now(),
                }
            }
        return True
