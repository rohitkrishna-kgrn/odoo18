# models/project_project.py
from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime


class ProjectProject(models.Model):
    _inherit = 'project.project'

    def action_mark_as_done(self):
        """Mark selected projects and all tasks as Done/Completed"""
        done_project_stage = self.env['project.project.stage'].search([('name', '=', 'Done')], limit=1)
        done_task_stage = self.env['project.task.type'].search([('name', '=', 'Done')], limit=1)

        if not done_project_stage or not done_task_stage:
            raise UserError("Cannot find 'Done' stage for projects or tasks.")

        for project in self:
            tasks = project.task_ids
            for task in tasks:
                # Skip already done tasks
                if task.stage_id == done_task_stage and task.state_additional == 'completed':
                    continue
                task.write({
                    'stage_id': done_task_stage.id,
                    'state_additional': 'completed',
                    'completed_date': datetime.now(),
                })

            # Check if all tasks are completed
            remaining_tasks = project.task_ids.filtered(lambda t: t.stage_id != done_task_stage)
            if not remaining_tasks:
                project.write({
                    'stage_id': done_project_stage.id,
                    'completed_date': datetime.now(),
                })

        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_mark_as_in_progress(self):
        """Mark selected projects and all tasks as In Progress"""
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only System Administrators can change project status in bulk.")

        in_progress_project_stage = self.env['project.project.stage'].search(
            [('name', '=', 'In Progress')], limit=1
        )
        in_progress_task_stage = self.env['project.task.type'].search(
            [('name', '=', 'In Progress')], limit=1
        )

        if not in_progress_project_stage or not in_progress_task_stage:
            raise UserError("Cannot find 'In Progress' stage for projects or tasks.")

        for project in self:
            tasks = project.task_ids

            for task in tasks:
                # Skip already in progress tasks
                if task.stage_id == in_progress_task_stage and task.state_additional == 'in_progress':
                    continue

                task.write({
                    'stage_id': in_progress_task_stage.id,
                    'state_additional': 'in_progress',
                })

            project.write({
                'stage_id': in_progress_project_stage.id,
            })

        return {'type': 'ir.actions.client', 'tag': 'reload'}