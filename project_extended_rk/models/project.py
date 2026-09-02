from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools.float_utils import float_compare
from datetime import timedelta
import logging

HOLD_TASK_STAGE_XMLID = 'project_extended_rk.project_task_type_on_hold'
# A task is considered finished if any of the three disagreeing "done" signals
# in this codebase says so (core state, custom state_additional, folded stage).
CLOSED_TASK_STATES = ('1_done', '1_canceled')


class ProjectProjectStage(models.Model):
    _inherit = 'project.project.stage'

    is_hold_stage = fields.Boolean(
        string="Counts as On Hold",
        help="Projects sitting in this stage are treated as On Hold: every open "
             "task under them is automatically moved to the 'On Hold' task stage "
             "and Additional State, and dropped from the PM workload views.",
    )


class ProjectTaskType(models.Model):
    _inherit = 'project.task.type'

    is_hold_stage = fields.Boolean(
        string="Counts as On Hold",
        help="Technical: the task stage the project-hold automation parks tasks "
             "in. Exactly one stage should carry this flag.",
    )


class ProjectProject(models.Model):
    _inherit = 'project.project'

    sale_order_id = fields.Many2one('sale.order', string="Sales Order")
    budgeted_amount = fields.Float(string="Budgeted Amount")
    calculated_advance_amount = fields.Float(string="Balance")
    customer_id = fields.Many2one(
        'res.partner',
        string="Customer",
        related='sale_order_id.partner_id',
        store=True,  # optional: store it in the database
    )
    dms_folder_id = fields.Many2one('dms.directory', string="DMS Folder", readonly=True)

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

    completed_date = fields.Datetime(string='Completed Date', readonly=True)

    is_on_hold = fields.Boolean(
        string="On Hold",
        compute='_compute_is_on_hold',
        store=True,
        help="True when the project stage is flagged as a hold stage, or the "
             "project update status is set to On Hold.",
    )

    @api.depends('stage_id', 'stage_id.is_hold_stage', 'last_update_status')
    def _compute_is_on_hold(self):
        for project in self:
            project.is_on_hold = bool(project.stage_id.is_hold_stage) or \
                project.last_update_status == 'on_hold'

    def _sync_task_hold_state(self):
        """Push the project hold status down onto its tasks.

        On hold  -> every open task moves to the 'On Hold' task stage and its
                    Additional State becomes 'On Hold'.
        Released -> tasks the automation parked there go back to the stage and
                    state they came from.
        """
        tasks = self.env['project.task'].search([('project_id', 'in', self.ids)])
        for project in self:
            project_tasks = tasks.filtered(lambda t: t.project_id == project)
            if project.is_on_hold:
                project_tasks.filtered(
                    lambda t: not t._is_task_closed()
                )._apply_hold()
            else:
                project_tasks._release_hold()

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

    @api.onchange('user_id')
    def _onchange_user_id_dedicated_manager_check(self):
        if self.user_id and not self.user_id.is_dedicated_manager:
            self.user_id = False
            return {
                'warning': {
                    'title': _("Invalid Project Manager"),
                    'message': _(
                        "Only users designated as Dedicated Project Managers can be "
                        "assigned as the Project Manager for this project. Please "
                        "select a user with the Dedicated Project Manager permission "
                        "enabled."
                    ),
                }
            }

    @api.constrains('user_id')
    def _check_user_id_is_dedicated_manager(self):
        for project in self:
            if project.user_id and not project.user_id.is_dedicated_manager:
                raise ValidationError(_(
                    "Only users designated as Dedicated Project Managers can be "
                    "assigned as the Project Manager for this project. Please "
                    "select a user with the Dedicated Project Manager permission "
                    "enabled."
                ))

    @api.model
    def create(self, vals):
        # Allow only users in group_project_manager to create projects
        if not self.env.user.has_group('project.group_project_manager'):
            raise UserError("You do not have the access rights to create projects.")
        # New client engagement: block until AML/KYC is marked Completed
        # (or an Administrator has recorded an override) for the linked order.
        if vals.get('sale_order_id'):
            self.env['sale.order'].browse(vals['sale_order_id'])._check_aml_gate()
        project = super().create(vals)
        if project.is_on_hold:
            project.sudo()._sync_task_hold_state()
        return project

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

        # Snapshot the keys *before* super(): core project.write() pops
        # 'last_update_status' out of this very dict when it converts the value
        # into a project.update record, so checking vals afterwards misses it.
        hold_keys_written = bool({'stage_id', 'last_update_status', 'active'} & set(vals))

        res = super(ProjectProject, self).write(vals)

        # Project put On Hold (or released) -> mirror it onto every child task.
        if hold_keys_written:
            self.sudo()._sync_task_hold_state()

        return res

        
class ProjectTask(models.Model):
    _inherit = 'project.task'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True)

    project_team_id = fields.Many2one('project.team', string='Assigned Team')
    team_member_ids = fields.Many2many('res.users', string='Team Members', required=True)
    allowed_user_ids = fields.Many2many('res.users', compute='_compute_allowed_users')
    task_budget = fields.Float(string="Task Budget")
    state_additional = fields.Selection(
        [
            ('new', 'New'),
            ('in_progress', 'In Progress'),
            ('on_hold', 'On Hold'),
            ('waiting_for_approval', 'Waiting for Approval'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Additional State',
        default='new',
        required=True,
    )
    completed_date = fields.Datetime(string='Completed Date', readonly=True)
    completed_this_week = fields.Boolean(compute='_compute_completed_periods', store=True)
    completed_this_month = fields.Boolean(compute='_compute_completed_periods', store=True)
    completed_this_year = fields.Boolean(compute='_compute_completed_periods', store=True)
    dms_folder_id = fields.Many2one('dms.directory', string="DMS Folder", readonly=True)
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

    is_on_hold = fields.Boolean(
        string="On Hold",
        compute='_compute_is_on_hold',
        store=True,
        index=True,
        help="Set when the task sits in the 'On Hold' stage or its Additional "
             "State is On Hold. On-hold tasks are excluded by default from the "
             "All Tasks / My Tasks workload views.",
    )
    hold_auto = fields.Boolean(
        string="Put On Hold Automatically",
        default=False,
        copy=False,
        help="Technical: the project-hold automation is the one that parked this "
             "task On Hold, so it is allowed to move it back when the project "
             "comes off hold. Tasks put on hold by hand are never released.",
    )
    hold_prev_stage_id = fields.Many2one(
        'project.task.type',
        string="Stage Before Hold",
        copy=False,
        ondelete='set null',
        help="Technical: the stage to restore when the project comes off hold.",
    )
    hold_prev_state_additional = fields.Char(
        string="Additional State Before Hold",
        copy=False,
        help="Technical: the Additional State to restore when the project comes "
             "off hold.",
    )

    @api.model
    def _hold_task_stage(self, projects=None):
        """The single 'On Hold' task stage, linked to `projects` on demand.

        Task stages are per-project in Odoo, so the shared hold stage has to be
        added to a project's stage list before a task of that project can sit
        in it - otherwise the kanban column and the form statusbar hide it.
        """
        stage = self.env.ref(HOLD_TASK_STAGE_XMLID, raise_if_not_found=False)
        if not stage:
            # The data record was renamed or removed - fall back to the flag.
            stage = self.env['project.task.type'].sudo().search(
                [('is_hold_stage', '=', True)], limit=1)
        if stage and projects:
            missing = projects - stage.project_ids
            if missing:
                stage.sudo().write({'project_ids': [(4, p.id) for p in missing]})
        return stage

    @api.depends('stage_id', 'stage_id.is_hold_stage', 'state_additional')
    def _compute_is_on_hold(self):
        for task in self:
            task.is_on_hold = bool(task.stage_id.is_hold_stage) or \
                task.state_additional == 'on_hold'

    def _is_task_closed(self):
        """Tasks carry three disagreeing 'finished' signals - trust any of them."""
        self.ensure_one()
        return (
            self.state in CLOSED_TASK_STATES
            or self.stage_id.fold
            or self.state_additional in ('completed', 'cancelled')
        )

    def _apply_hold(self):
        """Park the tasks in the On Hold stage / state, remembering where they were."""
        hold_stage = self._hold_task_stage(self.mapped('project_id'))
        for task in self:
            vals = {}
            if hold_stage and task.stage_id != hold_stage:
                vals['hold_prev_stage_id'] = task.stage_id.id
                vals['stage_id'] = hold_stage.id
            if task.state_additional != 'on_hold':
                vals['hold_prev_state_additional'] = task.state_additional
                vals['state_additional'] = 'on_hold'
            if not vals:
                # Already on hold - whoever set it keeps ownership of it, so a
                # hand-set hold (hold_auto False, e.g. the On Hold button) is
                # not quietly promoted to one the cascade may undo later.
                continue
            vals['hold_auto'] = True
            task.with_context(skip_team_member_notification=True).write(vals)

    def _fallback_open_stage(self):
        """First open stage of the task's project, used when nothing was remembered."""
        self.ensure_one()
        if not self.project_id:
            return self.env['project.task.type']
        return self.env['project.task.type'].sudo().search([
            ('project_ids', '=', self.project_id.id),
            ('fold', '=', False),
            ('is_hold_stage', '=', False),
        ], order='sequence, id', limit=1)

    def _release_hold(self):
        """Move automation-held tasks back to where they were before the hold."""
        # Only release tasks the automation parked itself; a hand-set hold stays.
        for task in self.filtered(lambda t: t.hold_auto):
            vals = {
                'hold_auto': False,
                'hold_prev_stage_id': False,
                'hold_prev_state_additional': False,
            }
            if task.stage_id.is_hold_stage:
                # The remembered stage is only usable if it still belongs to
                # the task's project - a task can be moved between projects
                # while it sits on hold.
                target = task.hold_prev_stage_id
                if not target or task.project_id not in target.project_ids:
                    target = task._fallback_open_stage()
                if target:
                    vals['stage_id'] = target.id
            if task.state_additional == 'on_hold':
                vals['state_additional'] = task.hold_prev_state_additional or 'new'
            task.with_context(skip_team_member_notification=True).write(vals)

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
            raise UserError("You do not have the access rights to create tasks.")
        task = super().create(vals)
        # A task created under an already-held project starts out On Hold.
        if task.project_id.is_on_hold and not task._is_task_closed():
            task.sudo()._apply_hold()
        return task
    
    def write(self, vals):
        # Skip assignment notifications when called from the transfer wizard
        # (the wizard sends its own, more informative transfer emails)
        if self.env.context.get('skip_team_member_notification'):
            return super(ProjectTask, self).write(vals)


        # Track the original team members before write
        old_team_members = {
            rec.id: rec.team_member_ids.sudo()
            for rec in self.sudo() if rec.team_member_ids
        }

        result = super(ProjectTask, self).write(vals)

        # Moved to another project -> take that project's hold status.
        if 'project_id' in vals:
            for task in self.sudo():
                if task.project_id.is_on_hold and not task._is_task_closed():
                    task._apply_hold()
                else:
                    task._release_hold()

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

            if task.state_additional != 'in_progress':
                raise ValidationError(("You can only log time on tasks that are in 'In Progress' state."))

            # Block saving a timesheet with zero hours
            unit_amount = vals.get('unit_amount', 0)
            if float_compare(unit_amount, 0.0, precision_digits=2) <= 0:
                raise ValidationError(("Please enter the hours spent. Timesheet cannot be saved without hours."))

            subtask_id = vals.get('subtask_id')

            # Skip parent-task remaining-hours check when a subtask is selected;
            # subtask_gk handles that validation with a clearer error message.
            if not subtask_id:
                remaining_hours = task.remaining_hours
                if float_compare(unit_amount, remaining_hours, precision_digits=2) == 1:
                    raise ValidationError(("The effective hours cannot exceed the remaining hours for this task!"))

            # Authorise against the subtask's team members when a subtask is selected,
            # otherwise fall back to the parent task's team members.
            if subtask_id:
                subtask = self.env['project.task'].browse(subtask_id)
                if self.env.user not in subtask.team_member_ids:
                    raise ValidationError(("You are not authorized to log time on this sub-task."))
            else:
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

                # Only validate hours when unit_amount is explicitly being changed
                if 'unit_amount' in vals:
                    unit_amount = vals['unit_amount']

                    # Block saving a timesheet with zero hours
                    if float_compare(unit_amount, 0.0, precision_digits=2) <= 0:
                        raise ValidationError(("Please enter the hours spent. Timesheet cannot be saved without hours."))

                    subtask_id = vals.get('subtask_id') or (
                        record._fields.get('subtask_id') and record.subtask_id.id
                    )

                    # Skip parent-task remaining-hours check when a subtask is selected;
                    # subtask_gk handles that validation with a clearer error message.
                    if not subtask_id:
                        remaining_hours = task.remaining_hours
                        if float_compare(unit_amount, remaining_hours, precision_digits=2) == 1:
                            raise ValidationError(("The effective hours cannot exceed the remaining hours for this task!"))

                # Authorise against the subtask's team members when a subtask is selected,
                # otherwise fall back to the parent task's team members.
                subtask_id = vals.get('subtask_id') or (
                    record._fields.get('subtask_id') and record.subtask_id.id
                )
                if subtask_id:
                    subtask = self.env['project.task'].browse(subtask_id)
                    if self.env.user not in subtask.team_member_ids:
                        raise ValidationError(("You are not authorized to log time on this sub-task."))
                else:
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