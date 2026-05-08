from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SubtaskCreateWizard(models.TransientModel):
    _name = 'subtask.create.wizard'
    _description = 'Create Sub-Task Wizard'

    parent_task_id = fields.Many2one(
        'project.task', string='Parent Task', readonly=True, required=True,
    )
    parent_task_name = fields.Char(
        string='Parent Task', readonly=True, compute='_compute_parent_info',
    )
    parent_allocated_hours = fields.Float(
        string='Parent Allocated Hours', readonly=True, compute='_compute_parent_info',
    )
    subtask_used_hours = fields.Float(
        string='Already Allocated to Sub-Tasks', readonly=True, compute='_compute_parent_info',
    )
    remaining_hours = fields.Float(
        string='Available Hours', readonly=True, compute='_compute_parent_info',
        help="Parent task hours not yet allocated to any sub-task.",
    )
    available_after = fields.Float(
        string='Available After Allocation', readonly=True, compute='_compute_available_after',
        help="Remaining hours after subtracting the hours being allocated to this sub-task.",
    )
    name = fields.Char(string='Sub-Task Name', required=True)
    user_ids = fields.Many2many(
        'res.users',
        'subtask_wizard_user_rel',   # explicit table – avoids auto-name conflicts with res.users
        'wizard_id',
        'user_id',
        string='Assign Users',
        domain=[('share', '=', False)],
    )
    allocated_hours = fields.Float(string='Allocated Hours', required=True, default=0.0)

    @api.depends(
        'parent_task_id',
        'parent_task_id.allocated_hours',
        'parent_task_id.child_ids.allocated_hours',
    )
    def _compute_parent_info(self):
        for rec in self:
            task = rec.parent_task_id
            if task:
                used = sum(task.child_ids.mapped('allocated_hours'))
                rec.parent_task_name = task.name
                rec.parent_allocated_hours = task.allocated_hours or 0.0
                rec.subtask_used_hours = used
                rec.remaining_hours = max(0.0, (task.allocated_hours or 0.0) - used)
            else:
                rec.parent_task_name = ''
                rec.parent_allocated_hours = 0.0
                rec.subtask_used_hours = 0.0
                rec.remaining_hours = 0.0

    @api.depends('remaining_hours', 'allocated_hours')
    def _compute_available_after(self):
        for rec in self:
            rec.available_after = rec.remaining_hours - (rec.allocated_hours or 0.0)

    @api.constrains('allocated_hours', 'parent_task_id')
    def _check_allocated_hours(self):
        for rec in self:
            if rec.allocated_hours <= 0:
                raise ValidationError(_("Allocated hours must be greater than zero."))
            parent = rec.parent_task_id
            used = sum(parent.child_ids.mapped('allocated_hours'))
            available = (parent.allocated_hours or 0.0) - used
            if rec.allocated_hours > available:
                raise ValidationError(
                    _("Sub-task hours cannot exceed parent task allocated hours.\n"
                      "Parent task has %.2f hour(s) available.") % available
                )

    def action_create_subtask(self):
        self.ensure_one()
        parent = self.parent_task_id

        used = sum(parent.child_ids.mapped('allocated_hours'))
        available = (parent.allocated_hours or 0.0) - used
        if self.allocated_hours <= 0:
            raise ValidationError(_("Allocated hours must be greater than zero."))
        if self.allocated_hours > available:
            raise ValidationError(
                _("Sub-task hours cannot exceed parent task allocated hours.\n"
                  "Parent task has %.2f hour(s) available.") % available
            )

        vals = {
            'name': self.name,
            'parent_id': parent.id,
            'project_id': parent.project_id.id,
            'allocated_hours': self.allocated_hours,
        }
        if self.user_ids:
            vals['user_ids'] = [(6, 0, self.user_ids.ids)]
            vals['team_member_ids'] = [(6, 0, self.user_ids.ids)]

        self.env['project.task'].sudo().create(vals)
        return {'type': 'ir.actions.act_window_close'}
