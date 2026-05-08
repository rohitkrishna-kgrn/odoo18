# my_project_stage_automation/models/project_task.py
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# project.task
# ─────────────────────────────────────────────────────────────────────────────

class ProjectTask(models.Model):
    _inherit = 'project.task'

    state_additional = fields.Selection(
        [
            ('new', 'New'),
            ('in_progress', 'In Progress'),
            ('waiting_for_approval', 'Waiting for Approval'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        string='Additional State',
        default='new',
        required=True,
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'project_task_invoice_rel',
        'task_id',
        'invoice_id',
        string='Invoices',
        domain=[('move_type', '=', 'out_invoice')],
    )
    user_id = fields.Many2one('res.users', string='Assigned to')
    auto_invoice = fields.Boolean(string='Auto Invoice', store=True, readonly=True)
    completed_date = fields.Datetime(string='Completed Date', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Sales Order Line')

    # ── Upcoming tasks: auto-cancel when created under a cancelled SO ─────────

    @api.model
    def create(self, vals):
        task = super().create(vals)
        try:
            so = task.project_id.sale_order_id if task.project_id else False
            if so and so.state == 'cancel':
                so_model = self.env['sale.order']
                task_stage = so_model._get_or_create_task_stage('Cancelled', task.project_id)
                task.sudo().with_context(skip_team_member_notification=True).write({
                    'stage_id': task_stage.id,
                    'state_additional': 'cancelled',
                })
                logger.info(
                    "[AUTO-CANCEL] Task '%s' auto-cancelled — SO '%s' is already cancelled.",
                    task.name, so.name,
                )
        except Exception:
            logger.exception("[AUTO-CANCEL] Failed to auto-cancel task '%s'.", task.name)
        return task

    # ── Workflow action buttons ───────────────────────────────────────────────

    def action_in_progress(self):
        self.ensure_one()
        if not self.team_member_ids:
            raise UserError("Cannot set task to 'In Progress' without assigned team members.")

        in_progress_stage = self.env['project.task.type'].sudo().search(
            [('name', '=', 'In Progress')], limit=1
        )
        if not in_progress_stage:
            raise UserError("The 'In Progress' stage for the task is not defined.")
        self.write({'stage_id': in_progress_stage.id})

        in_progress_project_stage = self.env['project.project.stage'].search(
            [('name', '=', 'In Progress')], limit=1
        )
        if not in_progress_project_stage:
            raise UserError("The 'In Progress' stage for the project is not defined.")
        if self.project_id:
            self.project_id.write({'stage_id': in_progress_project_stage.id})

        self.write({'state_additional': 'in_progress'})

        if self.project_id and self.project_id.sale_order_name:
            sale_order = self.env['sale.order'].sudo().search(
                [('name', '=', self.project_id.sale_order_name)], limit=1
            )
            if sale_order:
                if sale_order.order_status != 'opened':
                    sale_order.write({'order_status': 'opened'})
                    logger.info("[TASK] SO '%s' set to OPENED", sale_order.name)
            else:
                logger.warning("[TASK] No SO found with name '%s'", self.project_id.sale_order_name)
        return True

    def action_send_for_approval(self):
        self.ensure_one()
        if self.stage_id.name == 'Waiting For Approval':
            raise UserError("The task is already Waiting For Approval.")

        stage = self.env['project.task.type'].search(
            [('name', '=', 'Waiting For Approval')], limit=1
        )
        if not stage:
            raise UserError("The 'Waiting For Approval' stage for the task is not defined.")
        self.write({'stage_id': stage.id, 'state_additional': 'waiting_for_approval'})

    def action_approve(self):
        self.ensure_one()
        if self.stage_id.name == 'Completed':
            raise UserError("The task is already completed.")

        done_stage = self.env['project.task.type'].sudo().search(
            [('name', '=', 'Done')], limit=1
        )
        if not done_stage:
            raise UserError("The 'Done' task stage is not defined.")

        project = self.project_id
        if not project:
            raise UserError("The task is not associated with any project.")
        if self.env.user not in project.user_id:
            raise UserError("Only project managers can approve tasks.")

        self.write({
            'stage_id': done_stage.id,
            'state_additional': 'completed',
            'completed_date': fields.Datetime.now(),
        })

        if self.sale_line_id:
            self.sale_line_id.sudo().write(
                {'qty_delivered': self.sale_line_id.qty_delivered + 1}
            )

        all_done = all(t.stage_id.name == 'Done' for t in project.task_ids)
        if all_done:
            proj_done_stage = self.env['project.project.stage'].sudo().search(
                [('name', '=', 'Done')], limit=1
            )
            if not proj_done_stage:
                raise UserError("The 'Done' project stage is not defined.")
            project.sudo().write({
                'stage_id': proj_done_stage.id,
                'completed_date': fields.Datetime.now(),
            })

            approver = self.env.company.approver_user_id
            if approver and approver.email:
                self.env['mail.mail'].sudo().create({
                    'subject': f"Project '{project.name}' Completed",
                    'body_html': f"""
                        <p>Dear {approver.name},</p>
                        <p>Project <strong>{project.name}</strong> has been marked as
                        <span style="color:green;">Done</span>.</p>
                        <p>Completion Date: {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><em>KGRN Chartered Accountants</em></p>
                    """,
                    'email_to': approver.email,
                }).send()

        if self.project_id and self.project_id.sale_order_name:
            sale_order = self.env['sale.order'].sudo().search(
                [('name', '=', self.project_id.sale_order_name)], limit=1
            )
            if sale_order and sale_order.order_status != 'closed':
                sale_order.write({'order_status': 'closed'})
                logger.info("[TASK] SO '%s' set to Closed", sale_order.name)

        if self.auto_invoice:
            return self._create_task_budget_invoice()
        return True

    def action_retrieve(self):
        self.ensure_one()
        stage = self.env['project.task.type'].sudo().search(
            [('name', '=', 'In Progress')], limit=1
        )
        if not stage:
            raise UserError("The 'In Progress' stage for the task is not defined.")
        self.write({'stage_id': stage.id, 'state_additional': 'in_progress'})
        return True

    def _create_task_budget_invoice(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError("Please set a customer for the task.")

        existing = self.invoice_ids.filtered(
            lambda inv: inv.state == 'draft'
            and inv.amount_total == self.task_budget
            and inv.invoice_origin == self.name
        )
        if existing:
            return existing

        income_account = self.env['account.account'].search(
            [('account_type', '=', 'income')], limit=1
        )
        if not income_account:
            raise UserError("No income account found for invoice line.")

        sale_line = self.sale_line_id
        invoice = self.env['account.move'].with_context(
            automated_invoice_creation=True
        ).create({
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'invoice_user_id': self.user_id.id if self.user_id else self.env.user.id,
            'currency_id': self.company_id.currency_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': f'Task Budget for {self.name}',
                'quantity': 1,
                'price_unit': self.task_budget,
                'account_id': income_account.id,
                'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
                'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
            })],
        })
        self.invoice_ids = [(4, invoice.id)]
        return invoice


# ─────────────────────────────────────────────────────────────────────────────
# project.project
# ─────────────────────────────────────────────────────────────────────────────

class ProjectProject(models.Model):
    _inherit = 'project.project'

    completed_date = fields.Datetime(string='Completed Date', readonly=True)
    auto_invoice = fields.Boolean(string='Auto Invoice', default=True)

    # project_extended_rk declares this as compute='_compute_sale_order_name',
    # store=False.  We override it here to be a plain stored Char so that
    # _create_project_and_tasks() can persist the value at creation time.
    sale_order_name = fields.Char(
        string='Sale Order Name',
        compute=False,
        store=True,
    )

    # ── Upcoming projects: auto-cancel when created linked to a cancelled SO ──

    @api.model
    def create(self, vals):
        project = super().create(vals)
        try:
            if project.sale_order_id and project.sale_order_id.state == 'cancel':
                so_model = self.env['sale.order']
                cancelled_stage = so_model._get_or_create_project_stage('Cancelled')
                project.sudo().write({'stage_id': cancelled_stage.id})
                logger.info(
                    "[AUTO-CANCEL] Project '%s' auto-cancelled — SO '%s' is already cancelled.",
                    project.name, project.sale_order_id.name,
                )
        except Exception:
            logger.exception("[AUTO-CANCEL] Failed to auto-cancel project '%s'.", project.name)
        return project

    # ── Upcoming projects: auto-cancel when sale_order_id is (re-)linked ──────

    def write(self, vals):
        res = super().write(vals)
        if 'sale_order_id' in vals and vals['sale_order_id']:
            so_model = self.env['sale.order']
            cancelled_proj_stage = None
            for project in self:
                if not (project.sale_order_id and project.sale_order_id.state == 'cancel'):
                    continue
                try:
                    if cancelled_proj_stage is None:
                        cancelled_proj_stage = so_model._get_or_create_project_stage('Cancelled')
                    task_stage = so_model._get_or_create_task_stage('Cancelled', project)
                    project.sudo().write({'stage_id': cancelled_proj_stage.id})
                    all_tasks = self.env['project.task'].sudo().with_context(
                        active_test=False
                    ).search([('project_id', '=', project.id)])
                    if all_tasks:
                        all_tasks.sudo().with_context(
                            skip_team_member_notification=True
                        ).write({
                            'stage_id': task_stage.id,
                            'state_additional': 'cancelled',
                        })
                    logger.info(
                        "[AUTO-CANCEL] Project '%s' auto-cancelled (SO re-linked) — SO '%s' is cancelled.",
                        project.name, project.sale_order_id.name,
                    )
                except Exception:
                    logger.exception(
                        "[AUTO-CANCEL] Failed to auto-cancel project '%s'.", project.name
                    )
        return res
