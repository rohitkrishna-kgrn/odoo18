from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ProjectListTransferWizard(models.TransientModel):
    _name = 'project.list.transfer.wizard'
    _description = 'Transfer Selected Projects'

    project_ids = fields.Many2many(
        'project.project',
        'project_list_transfer_proj_rel',
        'wizard_id', 'project_id',
        string='Selected Projects',
    )
    current_manager_ids = fields.Many2many(
        'res.users',
        string='Current Project Manager(s)',
        compute='_compute_current_manager_ids',
    )
    to_user_id = fields.Many2one(
        'res.users',
        string='Transfer To',
    )

    @api.depends('project_ids')
    def _compute_current_manager_ids(self):
        for rec in self:
            rec.current_manager_ids = rec.project_ids.mapped('user_id')

    def action_transfer(self):
        self.ensure_one()

        if not self.to_user_id:
            raise ValidationError(_("Please select a user to transfer to."))

        done_project_stages = self.env['project.project.stage'].search([]).filtered(
            lambda s: s.name.lower() == 'done'
        )
        done_task_stages = self.env['project.task.type'].search([]).filtered(
            lambda s: s.name.lower() == 'done'
        )

        projects_to_transfer = self.project_ids.filtered(
            lambda p: not p.stage_id or p.stage_id.id not in done_project_stages.ids
        )

        if not projects_to_transfer:
            raise UserError(_("All selected projects are completed and cannot be transferred."))

        for project in projects_to_transfer:
            project.sudo().write({'user_id': self.to_user_id.id})
            tasks_to_transfer = project.task_ids.filtered(
                lambda t: not t.stage_id or t.stage_id.id not in done_task_stages.ids
            )
            if tasks_to_transfer:
                tasks_to_transfer.sudo().write({'user_ids': [(6, 0, [self.to_user_id.id])]})

        return {'type': 'ir.actions.act_window_close'}


class TaskListTransferWizard(models.TransientModel):
    _name = 'task.list.transfer.wizard'
    _description = 'Transfer Tasks in Selected Project'

    project_id = fields.Many2one(
        'project.project',
        string='Project',
    )
    current_manager_ids = fields.Many2many(
        'res.users',
        string='Project Manager(s)',
        compute='_compute_current_manager_ids',
    )
    task_ids = fields.Many2many(
        'project.task',
        'task_list_transfer_task_rel',
        'wizard_id', 'task_id',
        string='Tasks',
    )
    to_user_ids = fields.Many2many(
        'res.users',
        'task_list_transfer_user_rel',
        'wizard_id', 'user_id',
        string='Transfer To',
    )

    @api.depends('project_id')
    def _compute_current_manager_ids(self):
        for rec in self:
            rec.current_manager_ids = rec.project_id.user_id if rec.project_id else self.env['res.users']

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            done_task_stages = self.env['project.task.type'].search([]).filtered(
                lambda s: s.name.lower() == 'done'
            )
            tasks = self.project_id.task_ids.filtered(
                lambda t: not t.stage_id or t.stage_id.id not in done_task_stages.ids
            )
            self.task_ids = tasks
            self.to_user_ids = self.project_id.user_id if self.project_id.user_id else False
        else:
            self.task_ids = False
            self.to_user_ids = False

    def action_transfer(self):
        self.ensure_one()

        if not self.project_id:
            raise ValidationError(_("Please select a project."))
        if not self.task_ids:
            raise ValidationError(_("Please select at least one task to transfer."))
        if not self.to_user_ids:
            raise ValidationError(_("Please select at least one user to transfer to."))

        self.task_ids.sudo().write({'user_ids': [(6, 0, self.to_user_ids.ids)]})

        return {'type': 'ir.actions.act_window_close'}
