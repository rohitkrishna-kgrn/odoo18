from odoo import models, fields, api, _


class ProjectTask(models.Model):
    _inherit = 'project.task'

    enable_subtasks = fields.Boolean(string='Sub Tasks', default=False)

    subtask_allocated_hours = fields.Float(
        compute='_compute_gk_subtask_hours', store=True,
    )
    remaining_subtask_hours = fields.Float(
        compute='_compute_gk_subtask_hours', store=True,
    )
    subtask_progress = fields.Char(
        compute='_compute_gk_subtask_progress', store=True,
    )
    has_subtasks = fields.Boolean(
        compute='_compute_gk_has_subtasks', store=True,
    )

    # Timesheet lines logged against this task as a subtask
    timesheet_line_ids = fields.One2many(
        'account.analytic.line', 'subtask_id',
        string='Subtask Timesheet Lines',
    )
    timesheet_used_hours = fields.Float(
        compute='_compute_gk_timesheet_hours',
        string='Hours Used',
        store=False,
    )
    timesheet_remaining_hours = fields.Float(
        compute='_compute_gk_timesheet_hours',
        string='Hours Remaining',
        store=False,
    )

    @api.depends(
        'timesheet_line_ids.unit_amount',
        'timesheet_ids.unit_amount',
        'allocated_hours',
    )
    def _compute_gk_timesheet_hours(self):
        for task in self:
            # timesheet_ids  → logged directly on subtask form (task_id = subtask)
            # timesheet_line_ids → logged via Timesheets module (subtask_id = subtask)
            direct = sum(task.timesheet_ids.mapped('unit_amount'))
            via_field = sum(task.timesheet_line_ids.mapped('unit_amount'))
            used = direct + via_field
            task.timesheet_used_hours = used
            task.timesheet_remaining_hours = max(0.0, (task.allocated_hours or 0.0) - used)

    @api.depends('child_ids.allocated_hours', 'allocated_hours')
    def _compute_gk_subtask_hours(self):
        for task in self:
            used = sum(task.child_ids.mapped('allocated_hours'))
            task.subtask_allocated_hours = used
            task.remaining_subtask_hours = max(0.0, (task.allocated_hours or 0.0) - used)

    @api.depends('child_ids', 'child_ids.stage_id', 'child_ids.stage_id.fold')
    def _compute_gk_subtask_progress(self):
        for task in self:
            total = len(task.child_ids)
            if total == 0:
                task.subtask_progress = ''
            else:
                done = len(task.child_ids.filtered(
                    lambda t: t.stage_id and t.stage_id.fold
                ))
                task.subtask_progress = f"{done}/{total} Sub Tasks"

    @api.depends('child_ids')
    def _compute_gk_has_subtasks(self):
        for task in self:
            task.has_subtasks = bool(task.child_ids)

    def _get_remaining_usage(self, ids):
        """Return {task_id: used_hours} for the given task ids."""
        lines = self.env['account.analytic.line'].sudo().search([
            '|',
            ('task_id', 'in', ids),
            ('subtask_id', 'in', ids),
        ])
        usage = {}
        for line in lines:
            if line.task_id.id in ids:
                usage[line.task_id.id] = usage.get(line.task_id.id, 0.0) + line.unit_amount
            if line.subtask_id.id in ids:
                usage[line.subtask_id.id] = usage.get(line.subtask_id.id, 0.0) + line.unit_amount
        return usage

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        results = super().name_search(name=name, args=args, operator=operator, limit=limit)
        if not self.env.context.get('subtask_show_remaining'):
            return results

        ids = [r[0] for r in results]
        tasks = {t.id: t for t in self.browse(ids)}
        usage = self._get_remaining_usage(ids)

        return [
            (
                tid,
                '%s (%.2f remaining)' % (
                    tasks[tid].name,
                    max(0.0, (tasks[tid].allocated_hours or 0.0) - usage.get(tid, 0.0)),
                ),
            )
            for tid, _ in results
        ]

    def name_get(self):
        if not self.env.context.get('subtask_show_remaining'):
            return super().name_get()

        ids = self.ids
        usage = self._get_remaining_usage(ids)
        return [
            (
                task.id,
                '%s (%.2f remaining)' % (
                    task.name,
                    max(0.0, (task.allocated_hours or 0.0) - usage.get(task.id, 0.0)),
                ),
            )
            for task in self
        ]

    def action_open_subtask_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Sub-Task'),
            'res_model': 'subtask.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_parent_task_id': self.id},
        }
