from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    subtask_id = fields.Many2one(
        'project.task',
        string='Sub-Task',
        domain="[('parent_id', '=', task_id)]",
        help="Select a sub-task if the selected task has sub-tasks.",
    )
    task_has_subtasks = fields.Boolean(
        compute='_compute_task_has_subtasks',
        string='Task Has Sub-Tasks',
        store=False,
    )

    @api.depends('task_id', 'task_id.child_ids')
    def _compute_task_has_subtasks(self):
        for line in self:
            line.task_has_subtasks = bool(line.task_id and line.task_id.child_ids)

    subtask_remaining_hours = fields.Float(
        compute='_compute_subtask_remaining_hours',
        string='Sub-Task Remaining Hours',
        store=False,
    )

    @api.depends('subtask_id')
    def _compute_subtask_remaining_hours(self):
        for line in self:
            if line.subtask_id:
                line.subtask_remaining_hours = self._get_subtask_available(
                    line.subtask_id, exclude_record=line._origin
                )
            else:
                line.subtask_remaining_hours = 0.0

    def _get_subtask_available(self, subtask, exclude_record=None):
        """Return available hours for subtask across both logging paths."""
        domain_direct = [('task_id', '=', subtask.id)]
        domain_field = [('subtask_id', '=', subtask.id)]
        if exclude_record and exclude_record.id:
            domain_direct += [('id', '!=', exclude_record.id)]
            domain_field += [('id', '!=', exclude_record.id)]
        direct = sum(self.env['account.analytic.line'].sudo().search(domain_direct).mapped('unit_amount'))
        via_field = sum(self.env['account.analytic.line'].sudo().search(domain_field).mapped('unit_amount'))
        used = direct + via_field
        return max(0.0, (subtask.allocated_hours or 0.0) - used)

    def _check_subtask_hours(self, subtask, new_amount, current_amount=0.0, exclude_record=None):
        """Block save when new_amount exceeds available hours for the subtask.

        Counts hours from both logging paths:
          - task_id = subtask  (logged directly on subtask form)
          - subtask_id = subtask  (logged via Timesheets module)
        """
        allocated = subtask.allocated_hours
        available = self._get_subtask_available(subtask, exclude_record=exclude_record) + current_amount

        if float_compare(new_amount, available, precision_digits=2) != 1:
            return

        if float_compare(available, 0.0, precision_digits=2) <= 0:
            raise ValidationError(
                _("Allocated hours for sub-task \"%s\" are fully used "
                  "(%.2f h allocated, 0.00 h remaining).\n\n"
                  "To log more time, please submit an Extra Hours request "
                  "for this sub-task and wait for approval.")
                % (subtask.name, allocated)
            )
        raise ValidationError(
            _("Hours (%.2f h) exceed the remaining %.2f h for "
              "sub-task \"%s\" (%.2f h allocated).\n\n"
              "Reduce the hours to %.2f h or less, or submit an Extra Hours "
              "request for this sub-task.")
            % (new_amount, available, subtask.name, allocated, available)
        )

    @api.model
    def create(self, vals):
        unit_amount = vals.get('unit_amount', 0.0)
        subtask_id = vals.get('subtask_id')
        if subtask_id:
            subtask = self.env['project.task'].browse(subtask_id)
            self._check_subtask_hours(subtask, unit_amount)
        else:
            task_id = vals.get('task_id')
            if task_id:
                task = self.env['project.task'].browse(task_id)
                if task.parent_id:
                    self._check_subtask_hours(task, unit_amount)
        return super().create(vals)

    def write(self, vals):
        if 'subtask_id' in vals or 'unit_amount' in vals or 'task_id' in vals:
            for record in self:
                subtask_changing = 'subtask_id' in vals
                new_subtask_raw = vals.get('subtask_id') if subtask_changing else None
                subtask = (
                    self.env['project.task'].browse(new_subtask_raw)
                    if subtask_changing and new_subtask_raw
                    else record.subtask_id
                )
                new_amount = vals.get('unit_amount', record.unit_amount)

                if subtask:
                    current = 0.0 if subtask_changing else record.unit_amount
                    record._check_subtask_hours(subtask, new_amount, current, exclude_record=record)
                else:
                    # Check if the task itself is a subtask (direct form logging)
                    task_id = vals.get('task_id') or record.task_id.id
                    if task_id:
                        task = self.env['project.task'].browse(task_id)
                        if task.parent_id:
                            task_changing = 'task_id' in vals
                            current = 0.0 if task_changing else record.unit_amount
                            record._check_subtask_hours(task, new_amount, current, exclude_record=record)
        return super().write(vals)

    @api.onchange('task_id')
    def _onchange_task_id_clear_subtask(self):
        self.subtask_id = False
        self.unit_amount = 0.0

    @api.onchange('subtask_id')
    def _onchange_subtask_id_fill_hours(self):
        if self.subtask_id:
            self.unit_amount = 0.0
