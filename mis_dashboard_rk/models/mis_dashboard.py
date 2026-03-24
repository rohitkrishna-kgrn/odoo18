from odoo import models, fields, api

# Task Timesheet Summary Model
class TaskTimesheetSummary(models.Model):
    _name = 'task.timesheet.summary'
    _description = 'Task Timesheet Summary'
    _order = 'user_id'

    task_id = fields.Many2one('project.task', string='Task', required=True)
    user_id = fields.Many2one('res.users', string='User')
    hours_spent = fields.Float(string='Hours Spent')
    weightage_number = fields.Float(string='Weightage')
    total = fields.Float(string='Total')
    user_w_rate = fields.Float(
        string='User Weighted Rate',
        compute='_compute_user_w_rate'
    )

    @api.depends('total', 'task_id.timesheet_rate')
    def _compute_user_w_rate(self):
        for summary in self:
            summary.user_w_rate = (summary.hours_spent or 0.0) * (summary.task_id.timesheet_total or 0.0)

# Project Task Extensions
class ProjectTask(models.Model):
    _inherit = 'project.task'

    task_budget = fields.Float(string="Task Value", compute='_compute_task_budget', store=True, readonly=True)
    calculated_task_budget = fields.Float(string="Advance", compute='_compute_calculated_task_budget', store=True, readonly=True)
    team_member_ids = fields.Many2many('res.users', string='Team Members')
    allocated_hours = fields.Float(string="Allocated Hours", readonly=True)
    effective_hours = fields.Float(string="Time Spent", compute='_compute_effective_hours', store=True, readonly=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True)

    timesheet_ids = fields.One2many('account.analytic.line', 'task_id', string='Timesheets')
    timesheet_summary_ids = fields.One2many('task.timesheet.summary', 'task_id', string='Timesheet Summary', compute='_compute_timesheet_summary', store=False)
    timesheet_total = fields.Float(
        string='Timesheet Total',
        compute='_compute_timesheet_total',
        store=True
    )
    timesheet_rate = fields.Float(string='Timesheet W-Rate', compute='_compute_timesheet_rate', store=False)
    timesheet_user_total = fields.Float(string='Total of Users W-Rate', compute='_compute_timesheet_user_total', store=False)
    profit_loss_status = fields.Html(string="Profit / Loss", compute='_compute_profit_loss_status', store=True, readonly=True)
    completed_date = fields.Datetime(string="Completed Date", compute='_compute_group_sort')

    @api.depends('project_id')
    def _compute_group_sort(self):
        for task in self:
            task.completed_date = getattr(task, 'completed_date', 0.0)


    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.user_id')
    def _compute_timesheet_summary(self):
        summary_model = self.env['task.timesheet.summary']
        for task in self:
            # Clear any existing summaries for this task in DB
            summary_model.sudo().search([('task_id', '=', task.id)]).unlink()

            summary_vals = []
            for ts in task.timesheet_ids:
                user = ts.user_id
                weightage = user.employee_id.weightage_id.number if user.employee_id.weightage_id else 1.0
                summary_vals.append({
                    'task_id': task.id,
                    'user_id': user.id,
                    'hours_spent': ts.unit_amount,
                    'weightage_number': weightage,
                    'total': ts.unit_amount * weightage,
                })

            # Create the records in DB
            created = summary_model.sudo().create(summary_vals)
            # Assign them to the One2many (Odoo handles the relation automatically)
            task.timesheet_summary_ids = created


    @api.depends('project_id')
    def _compute_task_budget(self):
        for task in self:
            task.task_budget = getattr(task, 'task_budget', 0.0)
        
    @api.depends('timesheet_summary_ids.total')
    def _compute_timesheet_total(self):
        for task in self:
            task.timesheet_total = sum(task.timesheet_summary_ids.mapped('total'))

    @api.depends('project_id')
    def _compute_calculated_task_budget(self):
        for task in self:
            if task.project_id:
                project_tasks = self.env['project.task'].search([('project_id', '=', task.project_id.id)])
                num_tasks = len(project_tasks) or 1
                calculated_advance = getattr(task.project_id, 'calculated_advance_amount', 0.0)
                task.calculated_task_budget = calculated_advance / num_tasks
            else:
                task.calculated_task_budget = 0.0

    @api.depends('timesheet_ids.unit_amount')
    def _compute_effective_hours(self):
        for task in self:
            task.effective_hours = sum(task.timesheet_ids.mapped('unit_amount'))

    @api.depends('task_budget', 'calculated_task_budget', 'timesheet_total')
    def _compute_timesheet_rate(self):
        for task in self:
            total_budget = (task.task_budget or 0.0) + (task.calculated_task_budget or 0.0)
            task.timesheet_rate = total_budget / task.timesheet_total if task.timesheet_total else 0.0

    @api.depends('timesheet_summary_ids.user_w_rate')
    def _compute_timesheet_user_total(self):
        for task in self:
            task.timesheet_user_total = sum(task.timesheet_summary_ids.mapped('user_w_rate'))

    @api.depends('timesheet_user_total', 'task_budget', 'calculated_task_budget')
    def _compute_profit_loss_status(self):
        for task in self:
            total_budget = (task.task_budget or 0.0) + (task.calculated_task_budget or 0.0)
            diff = total_budget - (task.timesheet_user_total or 0.0)
            if diff > 0:
                task.profit_loss_status = f'<span class="btn btn-success">Profit ({diff:.2f})</span>'
            elif diff < 0:
                task.profit_loss_status = f'<span class="btn btn-danger">Loss ({abs(diff):.2f})</span>'
            else:
                task.profit_loss_status = f'<span class="btn btn-secondary">Neutral (0)</span>'
