from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProjectProject(models.Model):
    _inherit = 'project.project'

    reminder_schedule_ids = fields.One2many(
        'project.reminder.schedule', 'project_id', string='Reminder Schedules',
    )
    reminder_line_count = fields.Integer(
        compute='_compute_reminder_counts', string='Total Reminders',
    )
    reminder_upcoming_count = fields.Integer(
        compute='_compute_reminder_counts', string='Upcoming Reminders',
    )
    reminder_completed_count = fields.Integer(
        compute='_compute_reminder_counts', string='Completed Reminders',
    )
    is_closed_stage = fields.Boolean(
        compute='_compute_is_closed_stage', string='Is Closed Stage',
    )
    has_active_reminders = fields.Boolean(
        compute='_compute_has_active_reminders', string='Has Active Reminders',
    )

    @api.depends('reminder_schedule_ids.line_ids', 'reminder_schedule_ids.line_ids.state')
    def _compute_reminder_counts(self):
        for project in self:
            lines = project.reminder_schedule_ids.mapped('line_ids')
            project.reminder_line_count = len(lines)
            project.reminder_upcoming_count = len(lines.filtered(lambda l: l.state == 'upcoming'))
            project.reminder_completed_count = len(lines.filtered(lambda l: l.state == 'completed'))

    @api.depends('stage_id', 'stage_id.name')
    def _compute_is_closed_stage(self):
        closed = {'Done', 'Cancelled', 'Sent for GRN Approval'}
        for project in self:
            project.is_closed_stage = bool(project.stage_id and project.stage_id.name in closed)

    @api.depends('reminder_schedule_ids.state')
    def _compute_has_active_reminders(self):
        for project in self:
            project.has_active_reminders = any(
                s.state not in ('completed', 'cancelled')
                for s in project.reminder_schedule_ids
            )

    def action_open_reminder_wizard(self):
        self.ensure_one()
        active = self.reminder_schedule_ids.filtered(
            lambda s: s.state not in ('completed', 'cancelled')
        )
        if active:
            raise ValidationError(_(
                "A reminder schedule '%s' already exists for this project. "
                "Please complete or cancel it before adding a new one.",
                active[0].name,
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Reminder',
            'res_model': 'project.reminder.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_view_reminders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Project Reminders',
            'res_model': 'project.reminder.line',
            'view_mode': 'list,calendar,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }
