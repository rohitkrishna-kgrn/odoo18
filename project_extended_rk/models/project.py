from odoo import models, fields, api, _
from odoo.exceptions import AccessError
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare
from datetime import timedelta
import logging

class ProjectProject(models.Model):
    _inherit = 'project.project'

    sale_order_id = fields.Many2one('sale.order', string="Sales Order")
    budgeted_amount = fields.Float(string="Budgeted Amount")
    calculated_advance_amount = fields.Float(string="Balance")
    deadline = fields.Datetime(string="Deadline")
    customer_id = fields.Many2one(
        'res.partner',
        string="Customer",
        related='sale_order_id.partner_id',
        store=True,  # optional: store it in the database
    )
    dms_folder_id = fields.Many2one(
        'dms.directory', string="DMS Folder", readonly=True
    )

    sale_order_name = fields.Char(
        string="Sale Order Name",
        compute='_compute_sale_order_name',
        readonly=True,
        store=False,
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        compute='_compute_department_id',
        store=True
    )

    total_invoiced_amount = fields.Monetary(
        string="Total Invoiced",
        compute="_compute_invoice_amounts",
        currency_field="currency_id",
        store=True,
    )

    paid_invoice_amount = fields.Monetary(
        string="Paid Invoices",
        compute="_compute_invoice_amounts",
        currency_field="currency_id",
        store=True,
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
        store=True,
    )

    project_created_date = fields.Datetime(
        string="Project Created Date",
        compute="_compute_project_created_date",
        readonly=True,
    )

    total_project_value = fields.Monetary(
        string="Project Value",
        compute="_compute_invoice_amounts",
        currency_field="currency_id",
        store=True,
    )

    billable_type = fields.Selection([('billable', 'Billable'),('non_billable', 'Non-Billable')], string="Billing Type", default='billable')


    @api.depends("create_date")
    def _compute_project_created_date(self):
        for project in self:
            project.project_created_date = project.create_date

    @api.depends(
        "task_ids.sale_line_id.price_subtotal",
        "task_ids.sale_line_id.invoice_lines.move_id.state",
        "task_ids.sale_line_id.invoice_lines.price_subtotal",
        "task_ids.sale_line_id.invoice_lines.move_id.payment_state",
    )
    def _compute_invoice_amounts(self):
        for project in self:
            total_invoiced = 0.0
            total_paid = 0.0
            project_value = 0.0

            sale_lines = project.task_ids.mapped("sale_line_id")

            # ✅ Project total value (SO line value)
            for line in sale_lines:
                project_value += line.price_subtotal

            # ✅ Invoice values
            invoice_lines = sale_lines.mapped("invoice_lines").filtered(
                lambda l: l.move_id.state == "posted"
            )

            for line in invoice_lines:
                total_invoiced += line.price_subtotal

                if line.move_id.payment_state in ("paid", "partial"):
                    total_paid += line.price_subtotal

            project.total_project_value = project_value
            project.total_invoiced_amount = total_invoiced
            project.paid_invoice_amount = total_paid

    @api.depends('user_id')
    def _compute_department_id(self):
        for record in self:
            employee = self.env['hr.employee'].search([('user_id', '=', record.user_id.id)], limit=1)
            record.department_id = employee.department_id.id if employee else False

    def _compute_sale_order_name(self):
        for project in self:
            if project.sale_order_id:
                # If linked sale_order_id exists, show its name
                project.sale_order_name = project.sale_order_id.name
            else:
                # Otherwise, try to find latest sale order for the partner
                sale_order = self.env['sale.order'].search([
                    ('partner_id', '=', project.partner_id.id),
                    ('state', 'in', ['sale', 'done'])
                ], order='date_order desc', limit=1)
                project.sale_order_name = sale_order.name if sale_order else False

    @api.model
    def create(self, vals):
        # Allow only users in group_project_manager to create projects
        if not self.env.user.has_group('project.group_project_manager'):
            raise AccessError("You do not have the access rights to create projects.")
        return super().create(vals)

    @api.model
    def is_admin(self):
        return self.env.user.has_group('base.group_system')  # System/Settings group = Admin

    def write(self, vals):
        current_user = self.env.user

        # Prevent unauthorized project manager change
        if 'user_id' in vals and not current_user.project_manager_change_permission:
            raise UserError(_("You don't have permission to change the Project Manager."))

        # Prevent manual change to allocated_hours
        # if 'allocated_hours' in vals:
        #     raise UserError(_("You cannot modify the 'Allocated Hours' field directly."))

        return super(ProjectProject, self).write(vals)

        
class ProjectTask(models.Model):
    _inherit = 'project.task'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True)

    project_team_id = fields.Many2one('project.team', string='Assigned Team')
    team_member_ids = fields.Many2many('res.users', string='Team Members', required=True)
    allowed_user_ids = fields.Many2many('res.users', compute='_compute_allowed_users')
    task_budget = fields.Float(string="Task Budget")
    completed_this_week = fields.Boolean(compute='_compute_completed_periods', store=True)
    completed_this_month = fields.Boolean(compute='_compute_completed_periods', store=True)
    completed_this_year = fields.Boolean(compute='_compute_completed_periods', store=True)
    dms_folder_id = fields.Many2one(
        'dms.directory', string="DMS Folder", readonly=True
    )
    customer_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='project_id.partner_id',
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='project_id.partner_id',
        store=True,
        readonly=True,
    )
    billable_type = fields.Selection([('billable', 'Billable'),('non_billable', 'Non-Billable')], string="Billing Type", default='billable')
    
    @api.depends('completed_date')
    def _compute_completed_periods(self):
        user_tz = self.env.user.tz or 'UTC'
        now = fields.Datetime.context_timestamp(self.env.user, fields.Datetime.now())
        
        start_week = now - timedelta(days=now.weekday())
        end_week = start_week + timedelta(days=6, hours=23, minutes=59, seconds=59)
        
        start_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            start_next_month = start_month.replace(year=now.year+1, month=1)
        else:
            start_next_month = start_month.replace(month=now.month+1)
        end_month = start_next_month - timedelta(seconds=1)
        
        start_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_year = start_year.replace(year=now.year + 1) - timedelta(seconds=1)

        for rec in self:
            if rec.completed_date:
                dt = fields.Datetime.context_timestamp(self.env.user, fields.Datetime.from_string(rec.completed_date))
                rec.completed_this_week = start_week <= dt <= end_week
                rec.completed_this_month = start_month <= dt <= end_month
                rec.completed_this_year = start_year <= dt <= end_year
            else:
                rec.completed_this_week = False
                rec.completed_this_month = False
                rec.completed_this_year = False

    @api.depends('project_team_id')
    def _compute_allowed_users(self):
        for task in self:
            if task.project_team_id:
                task.allowed_user_ids = task.project_team_id.member_ids

    @api.onchange('project_team_id')
    def _onchange_project_team(self):
        if self.project_team_id:
            self.team_member_ids = self.project_team_id.member_ids
            return {
                'domain': {'team_member_ids': [('id', 'in', self.project_team_id.member_ids.ids)]}
            }
        else:
            self.team_member_ids = False
            return {
                'domain': {'team_member_ids': [('id', '=', 0)]}
            }

    def update_user_id(self):
        for task in self:
            task.user_id = task.manager_id.id if hasattr(task, 'manager_id') else False

    @api.model
    def create(self, vals):
        # Allow only users in group_project_manager to create tasks
        if not self.env.user.has_group('project.group_project_manager'):
            raise AccessError("You do not have the access rights to create tasks.")
        return super().create(vals)
    
    def write(self, vals):
        # Track the original team members before write
        old_team_members = {
            rec.id: rec.team_member_ids.sudo()
            for rec in self.sudo() if rec.team_member_ids
        }

        result = super(ProjectTask, self).write(vals)

        if 'team_member_ids' in vals:
            for task in self:
                old_members = old_team_members.get(task.id, self.env['res.users'])
                new_members = task.team_member_ids

                # Find newly added members
                added_members = new_members - old_members

                # Send notification to each new member
                for user in added_members:
                    if not user.partner_id.email:
                        continue  # Skip if the user doesn't have an email

                    html_body = f"""
                        <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
                            <p>Dear <strong>{user.name}</strong>,</p>

                            <p>You have been <strong>assigned</strong> to a new task in Odoo:</p>

                            <table style="border-collapse: collapse; margin: 10px 0;">
                                <tr>
                                    <td style="padding: 4px 8px; font-weight: bold;">Task:</td>
                                    <td style="padding: 4px 8px;">{task.name}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 4px 8px; font-weight: bold;">Project:</td>
                                    <td style="padding: 4px 8px;">{task.project_id.name or 'N/A'}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 4px 8px; font-weight: bold;">Deadline:</td>
                                    <td style="padding: 4px 8px;">{task.date_deadline or 'Not Set'}</td>
                                </tr>
                            </table>

                            <p>You can view the task directly by logging into the system.</p>

                            <p style="margin-top: 20px;">Best regards,<br/>
                            <em>KGRN Chartered Accountants</em></p>
                        </div>
                    """

                    self.env['mail.mail'].sudo().create({
                        'subject': f'New Task Assigned: {task.name}',
                        'body_html': html_body,
                        'email_to': user.partner_id.email,
                        'auto_delete': True,
                    }).send()

        return result

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    @api.model
    def create(self, vals):
        if vals.get('task_id'):
            task = self.env['project.task'].browse(vals['task_id'])
            
            # Check if task.state_additional is 'in_progress'
            if task.state_additional != 'in_progress':
                raise ValidationError(("You can only log time on tasks that are in 'In Progress' state."))

            effective_hours = vals.get('unit_amount', 0)
            remaining_hours = task.remaining_hours

            if float_compare(effective_hours, remaining_hours, precision_digits=2) == 1:
                raise ValidationError(("The effective hours cannot exceed the remaining hours for this task!"))

            # Check if current user is in the allowed team members of the task
            if self.env.user not in task.team_member_ids:
                raise ValidationError(("You are not authorized to log time on this task."))

        return super(AccountAnalyticLine, self).create(vals)

    def write(self, vals):
        for record in self:
            task_id = vals.get('task_id') or record.task_id.id
            if task_id:
                task = self.env['project.task'].browse(task_id)
                
                if task.state_additional != 'in_progress':
                    raise ValidationError(("You can only log time on tasks that are in 'In Progress' state."))

                effective_hours = vals.get('unit_amount', 0)
                remaining_hours = task.remaining_hours

                if float_compare(effective_hours, remaining_hours, precision_digits=2) == 1:
                    raise ValidationError(("The effective hours cannot exceed the remaining hours for this task!"))

                # Check if current user is in the allowed team members of the task
                if self.env.user not in task.team_member_ids:
                    raise ValidationError(("You are not authorized to log time on this task."))

        return super(AccountAnalyticLine, self).write(vals)

class ProjectTeam(models.Model):
    _name = 'project.team'
    _description = 'Project Team'

    name = fields.Char(string='Team Name', required=True)
    member_ids = fields.Many2many('res.users', string='Team Members')

class ResUsers(models.Model):
    _inherit = 'res.users'

    project_manager_change_permission = fields.Boolean(
        string='Project Manager Change Permission',
        default=False
    )