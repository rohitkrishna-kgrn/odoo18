# my_project_stage_automation/models/project_task.py
from odoo import models, fields, api
from odoo.exceptions import UserError, AccessError
import logging
logger = logging.getLogger(__name__)

class ProjectTask(models.Model):
    _inherit = 'project.task'

    state_additional = fields.Selection(
        [
            ('new', 'New'),
            ('in_progress', 'In Progress'),
            ('waiting_for_approval', 'Waiting for Approval'),
            ('completed', 'Completed')
        ],
        string='Additional State',
        default='new',
        required=True
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'project_task_invoice_rel',
        'task_id',
        'invoice_id',
        string='Invoices',
        domain=[('move_type', '=', 'out_invoice')]
    )
    user_id = fields.Many2one('res.users', string='Assigned to')
    auto_invoice = fields.Boolean(string="Auto Invoice", store=True, readonly=True)

    completed_date = fields.Datetime(string='Completed Date', readonly=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Sales Order Line')

    def _create_task_budget_invoice(self):
        self.ensure_one()

        if not self.partner_id:
            raise UserError("Please set a customer for the task.")

        existing_invoice = self.invoice_ids.filtered(
            lambda inv: inv.state == 'draft' and
                        inv.amount_total == self.task_budget and
                        inv.invoice_origin == self.name
        )
        if existing_invoice:
            return existing_invoice

        income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
        if not income_account:
            raise UserError("No income account found for invoice line.")

        sale_line = self.sale_line_id  # Assuming task is linked to a Sale Order Line

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_origin': self.name,
            'invoice_user_id': self.user_id.id if self.user_id else self.env.user.id,
            'currency_id': self.company_id.currency_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': f'Task Budget for Task {self.name}',
                'quantity': 1,
                'price_unit': self.task_budget,
                'account_id': income_account.id,
                'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
                'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
            })],
        }

        invoice = self.env['account.move'].with_context(automated_invoice_creation=True).create(invoice_vals)
        self.invoice_ids = [(4, invoice.id)]
        return invoice


    def action_in_progress(self):
        """ Set task status to 'In Progress' """
        self.ensure_one()  # Ensures only one task is being processed

        # Check if the task is already in "In Progress"
        # if self.stage_id.name == 'In Progress':
        #     raise UserError("The task is already in progress."

        if not self.team_member_ids:
            raise UserError("Cannot set task to 'In Progress' without assigned team members.")
        
        # Get the "In Progress" stage for the task
        in_progress_stage = self.env['project.task.type'].sudo().search([('name', '=', 'In Progress')], limit=1)
        if not in_progress_stage:
            raise UserError("The 'In Progress' stage for the task is not defined.")
        
        # Set the task's stage to "In Progress"
        self.write({'stage_id': in_progress_stage.id})

         # Get the "In Progress" stage for the project
        in_progress_project_stage = self.env['project.project.stage'].search([('name', '=', 'In Progress')], limit=1)
        if not in_progress_project_stage:
            raise UserError("The 'In Progress' stage for the project is not defined.")
        
        # Set the project's stage to "In Progress"
        if self.project_id:
            self.project_id.write({'stage_id': in_progress_project_stage.id})
        
        # Set the task's additional state to 'In Progress'
        self.write({'state_additional': 'in_progress'})

        if self.project_id and self.project_id.sale_order_name:
            sale_order = self.env['sale.order'].sudo().search([('name', '=', self.project_id.sale_order_name)], limit=1)
            if sale_order:
                if sale_order.order_status != 'opened':
                    sale_order.write({'order_status': 'opened'})
                    logger.info(f"[TASK IN PROGRESS] Sale Order '{sale_order.name}' set to OPENED")
                else:
                    logger.info(f"[TASK IN PROGRESS] Sale Order '{sale_order.name}' already OPENED")
            else:
                logger.warning(f"[TASK IN PROGRESS] No Sale Order found with name '{self.project_id.sale_order_name}'")
        else:
            logger.warning(f"[TASK IN PROGRESS] Project {self.project_id.name} has no sale_order_name set")

        return True

    def action_send_for_approval(self):
        """ Set task status to 'Waiting For Approval' """
        self.ensure_one()  # Ensures only one task is being processed

        # Check if the task is already in "In Progress"
        if self.stage_id.name == 'Waiting For Approval':
            raise UserError("The task is already Waiting For Approval.")
        
        # Get the "In Progress" stage for the task
        in_progress_stage = self.env['project.task.type'].search([('name', '=', 'Waiting For Approval')], limit=1)
        if not in_progress_stage:
            raise UserError("The 'Waiting For Approval' stage for the task is not defined.")
        
        # Set the task's stage to "In Progress"
        self.write({'stage_id': in_progress_stage.id})

        # Set the task's additional state to 'In Progress'
        self.write({'state_additional': 'waiting_for_approval'})

    def action_approve(self):
        """Set task status to 'Completed' and handle sale order delivery/invoice logic with elevated permissions."""
        self.ensure_one()  # Ensure only one task

        # Prevent double completion
        if self.stage_id.name == 'Completed':
            raise UserError("The task is already completed.")

        # Get the "Completed" stage for tasks
        in_progress_stage = self.env['project.task.type'].sudo().search([('name', '=', 'Done')], limit=1)
        if not in_progress_stage:
            raise UserError("The 'Completed' stage for the task is not defined.")

        project = self.project_id
        if not project:
            raise UserError("The task is not associated with any project.")

        # Check if the user is a project manager
        if self.env.user not in project.user_id:
            raise UserError("Only project managers can approve tasks.")

        # Update task stage and fields
        self.write({
            'stage_id': in_progress_stage.id,
            'state_additional': 'completed',
            'completed_date': fields.Datetime.now()
        })

        # Increment delivered quantity (with sudo)
        if self.sale_line_id:
            self.sale_line_id.sudo().write({
                'qty_delivered': self.sale_line_id.qty_delivered + 1
            })

        # Check if all project tasks are completed
        all_tasks_completed = all(
            task.stage_id.name == 'Done' for task in project.task_ids
        )

        if all_tasks_completed:
            done_stage = self.env['project.project.stage'].sudo().search([('name', '=', 'Done')], limit=1)
            if not done_stage:
                raise UserError("The 'Done' stage for the project is not defined.")

            project.sudo().write({
                'stage_id': done_stage.id,
                'completed_date': fields.Datetime.now()
            })

            company = self.env.company  # get current company
            approver = company.approver_user_id

            if approver and approver.email:
                subject = f"Project '{project.name}' Completed"
                body_html = f"""
                <html>
                <head>
                    <style>
                        body {{
                            font-family: Arial, sans-serif;
                            color: #000000;
                            padding: 20px;
                        }}
                        .container {{
                            max-width: 600px;
                            margin: auto;
                            background: white;
                            border-radius: 8px;
                            box-shadow: 0 0 10px rgba(0,0,0,0.1);
                            padding: 30px;
                        }}
                        h2 {{
                            color: #f25d23;
                        }}
                        p {{
                            font-size: 16px;
                            line-height: 1.5;
                        }}
                        .footer {{
                            margin-top: 30px;
                            font-size: 12px;
                            color: #999;
                            border-top: 1px solid #eee;
                            padding-top: 10px;
                            text-align: center;
                        }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h2>Project Completed Successfully!</h2>
                        <p>Dear {approver.name},</p>
                        <p>We are pleased to inform you that the project <strong>{project.name}</strong> has been marked as <span style="color:green;">Done</span>, as all its tasks are completed.</p>
                        <p>Completion Date: {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p class="footer">KGRN Chartered Accountants.</p>
                    </div>
                </body>
                </html>
                """

                # Create and send the email
                mail = self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body_html,
                    'email_to': approver.email,
                })
                mail.sudo().send()

        if self.project_id and self.project_id.sale_order_name:
            sale_order = self.env['sale.order'].sudo().search([('name', '=', self.project_id.sale_order_name)], limit=1)
            if sale_order:
                if sale_order.order_status != 'closed':
                    sale_order.write({'order_status': 'closed'})
                    logger.info(f"[TASK IN PROGRESS] Sale Order '{sale_order.name}' set to Closed")
                else:
                    logger.info(f"[TASK IN PROGRESS] Sale Order '{sale_order.name}' already Closed")
            else:
                logger.warning(f"[TASK IN PROGRESS] No Sale Order found with name '{self.project_id.sale_order_name}'")
        else:
            logger.warning(f"[TASK IN PROGRESS] Project {self.project_id.name} has no sale_order_name set")

        # If task is marked for auto-invoicing
        if self.auto_invoice:
            invoice = self._create_task_budget_invoice()
            return invoice

        return True

    
    def action_retrieve(self):
        """ Retrieve task back to 'In Progress' from 'Waiting for Approval' """
        self.ensure_one()

        # Restrict to Admins only
        # if not self.env.user._is_admin():
        #     raise AccessError("Only administrators can retrieve tasks.")

        # Get the "In Progress" stage for the task
        in_progress_stage = self.env['project.task.type'].sudo().search([('name', '=', 'In Progress')], limit=1)
        if not in_progress_stage:
            raise UserError("The 'In Progress' stage for the task is not defined.")

        self.write({
            'stage_id': in_progress_stage.id,
            'state_additional': 'in_progress'
        })
        return True

class ProjectProject(models.Model):
    _inherit = 'project.project'

    completed_date = fields.Datetime(string='Completed Date', readonly=True)
    auto_invoice = fields.Boolean(string="Auto Invoice", default=True)
    sale_order_name = fields.Char(
        string="Sale Order Name",
    )