from odoo import models, fields, api

class PlanningStage(models.Model):
    _name = 'planning.stage'
    _description = 'Planning Stage'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(string='Folded in Kanban')
    active = fields.Boolean(default=True)
    selection_key = fields.Selection([
        ('new', 'New'),
        ('today', 'Today'),
        ('this_week', 'This Week'),
        ('this_month', 'This Month'),
        ('later', 'Later'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], required=True, string='Planning Stage Key')


class Planning(models.Model):
    _name = 'planning.rk'
    _description = 'Planning Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Task Name', required=True, tracking=True)
    task_id = fields.Many2one('project.task', string='Task', required=True, ondelete='cascade', tracking=True)
    project_id = fields.Many2one('project.project', string='Project', store=True, required=True, tracking=True)
    deadline = fields.Date(string='Deadline', readonly=True, store=True)

    stage_id = fields.Many2one(
        'planning.stage',
        string='Stage',
        default=lambda self: self.env.ref('planning_rk.stage_new', raise_if_not_found=False).id,
        tracking=True,
        group_expand='_read_group_stage_id',
    )
    description = fields.Text(string='Description')

    @api.model
    def _read_group_stage_id(self, stages, domain):
        search_domain = ['|', ('id', 'in', stages.ids), ('fold', '=', False)]
        return self.env['planning.stage'].search(search_domain)

    @api.onchange('stage_id')
    def _onchange_stage_id(self):
        if self.stage_id and self.task_id:
            self.task_id.planning_stage = self.stage_id.selection_key

    @api.onchange('task_id')
    def _onchange_task_id(self):
        if self.task_id:
            self.project_id = self.task_id.project_id
            self.deadline = self.task_id.date_deadline

    @api.model
    def create(self, vals):
        # Set deadline from task if not provided
        if vals.get('task_id') and not vals.get('deadline'):
            task = self.env['project.task'].browse(vals['task_id'])
            vals['deadline'] = task.date_deadline

        record = super().create(vals)

        if record.stage_id and record.task_id and not self.env.context.get('from_task'):
            record.task_id.with_context(from_planning=True).write({
                'planning_stage': record.stage_id.selection_key,
                'planning_id': record.id
            })
        return record

    def write(self, vals):
        res = super().write(vals)
        if 'stage_id' in vals:
            for rec in self:
                if rec.stage_id and rec.task_id and not self.env.context.get('from_task'):
                    if rec.task_id.planning_stage != rec.stage_id.selection_key:
                        rec.task_id.with_context(from_planning=True).write({
                            'planning_stage': rec.stage_id.selection_key
                        })
        return res

    def unlink(self):
        for rec in self:
            if rec.task_id and not self.env.context.get('from_task'):
                rec.task_id.with_context(from_planning=True).write({
                    'planning_stage': False,
                    'planning_id': False
                })
        return super().unlink()
