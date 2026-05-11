from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Optional: Add related field to link back to the created project
    project_id = fields.Many2one('project.project', string='Linked Project')


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    billable_type = fields.Selection([('billable', 'Billable'),('non_billable', 'Non-Billable')], string="Billing Type", default='billable')

    def action_confirm(self):
        """Override confirmation to always show the confirmation wizard."""

        if not self.env.context.get('skip_advance_check'):
            for order in self:
                paid_invoices = order.invoice_ids.filtered(lambda inv:
                    inv.state == 'posted' and
                    inv.payment_state in ['paid', 'in_payment', 'partial'] and
                    inv.advance_invoice
                )
                total_paid = sum(inv.amount_total - inv.amount_residual for inv in paid_invoices)

                wizard = self.env['sale.order.advance.confirm.wizard'].create({
                    'order_id': order.id,
                    'advance_amount': order.advance_amount,
                    'paid_amount': total_paid,
                })
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Order Confirmation'),
                    'res_model': 'sale.order.advance.confirm.wizard',
                    'res_id': wizard.id,
                    'view_mode': 'form',
                    'target': 'new',
                }

        res = super(SaleOrder, self).action_confirm()

        # ✅ Then create projects/tasks
        for order in self:
            if order.order_line:
                calculated_advance_amount = (order.advance_amount or 0.0) / len(order.order_line)
                for line in order.order_line.filtered(lambda l: l.product_uom_qty > 0):
                    self._create_project_and_tasks(line, calculated_advance_amount)

        return res

    def _create_advance_invoice(self):
        self.ensure_one()

        if not self.partner_invoice_id:
            raise UserError("Please set an invoice address for the customer.")

        existing_invoice = self.invoice_ids.filtered(
            lambda inv: inv.state == 'draft' and
                        inv.amount_total == self.advance_amount and
                        inv.invoice_origin == self.name
        )
        if existing_invoice:
            return

        income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
        if not income_account:
            raise UserError("No income account found for advance invoice line.")

        sale_line = self.order_line[:1]  # Optional reference

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_invoice_id.id,
            'invoice_origin': self.name,
            'invoice_user_id': self.user_id.id,
            'currency_id': self.currency_id.id,
            'invoice_payment_term_id': self.payment_term_id.id,
            'advance_invoice': True,
            'invoice_line_ids': [(0, 0, {
                'name': 'Advance Payment',
                'quantity': 1,
                'price_unit': self.advance_amount,
                'account_id': income_account.id,
                'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
                'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
            })],
        }

        invoice = self.env['account.move'].with_context(automated_invoice_creation=True).create(invoice_vals)
        return invoice
    

    # @api.model
    # def _create_project_and_tasks(self, order_line, calculated_advance_amount):
    #     """Create a project and tasks linked to the sale order line."""

    #     Project = self.env['project.project'].sudo()
    #     Task = self.env['project.task'].sudo()

    #     project_amount = order_line.price_unit * order_line.product_uom_qty if order_line.product_uom_qty else 0
    #     advance_diff = project_amount - calculated_advance_amount
    #     sale_order = order_line.order_id

    #     project_vals = {
    #         'name': f"{sale_order.name} - {order_line.product_id.name} - {order_line.name}",
    #         'sale_order_id': sale_order.id,
    #         'partner_id': sale_order.partner_id.id,
    #         'company_id': order_line.company_id.id,
    #         'customer_id': sale_order.partner_id.id,
    #         'description': order_line.name or order_line.product_id.name,
    #         'user_id': order_line.manager_id.id if hasattr(order_line, 'manager_id') else False,
    #         'allocated_hours': getattr(order_line, 'estimated_hours', 0.0),
    #         'active': True,
    #         'calculated_advance_amount': calculated_advance_amount,
    #         'date_start': order_line.engagement_start,
    #         'date': order_line.engagement_end,
    #         'auto_invoice': sale_order.auto_invoice,
    #         'budgeted_amount': advance_diff,
    #         'deadline': order_line.deadline,
    #     }

    #     project = Project.create(project_vals)
    #     new_stage = self.env.ref('project.project_stage_0')

    #     task_amount = advance_diff / order_line.product_uom_qty if order_line.product_uom_qty else 0.0
    #     estimated_hours = getattr(order_line, 'estimated_hours', 0.0)

    #     tasks_to_create = []
    #     for i in range(int(order_line.product_uom_qty)):
    #         task_vals = {
    #             'name': f"Task {i + 1} for {order_line.product_id.name}",
    #             'project_id': project.id,
    #             'sale_order_id': sale_order.id,
    #             'sale_line_id': order_line.id,
    #             'partner_id': sale_order.partner_id.id,
    #             'company_id': order_line.company_id.id,
    #             'user_ids': False,
    #             'description': order_line.name or order_line.product_id.name,
    #             'stage_id': new_stage.id,
    #             'auto_invoice': sale_order.auto_invoice,
    #             'allocated_hours': estimated_hours / order_line.product_uom_qty if order_line.product_uom_qty > 0 else 0.0,
    #             'task_budget': task_amount,
    #             'date_deadline': order_line.deadline,
    #         }
    #         tasks_to_create.append(task_vals)

    #     Task.create(tasks_to_create)
    #     order_line.write({'project_id': project.id})

    #     # Optional: Notify user assigned to the project
    #     if project.user_id and project.user_id.email:
    #         template = self.env.ref('project_extended_rk.project_creation_email_template', raise_if_not_found=False)
    #         if template:
    #             template.send_mail(project.id, force_send=True)
    #         else:
    #             project.user_id.partner_id.message_post(
    #                 subject=_("New Project Created"),
    #                 body=_("A new project '%s' has been created and assigned to you.") % project.name,
    #                 message_type="notification",
    #                 subtype_xmlid="mail.mt_comment"
    #             )

    @api.model
    def _create_project_and_tasks(self, order_line, calculated_advance_amount):
        """Create a project and tasks linked to the sale order line."""

        Project = self.env['project.project'].sudo()
        Task = self.env['project.task'].sudo()

        project_amount = order_line.price_unit * order_line.product_uom_qty if order_line.product_uom_qty else 0
        advance_diff = project_amount - calculated_advance_amount
        sale_order = order_line.order_id

        project_vals = {
            'name': f"{sale_order.name} - {order_line.product_id.name} - {order_line.name}",
            'sale_order_name': sale_order.name.strip(),
            'sale_order_id': sale_order.id,
            'partner_id': sale_order.partner_id.id,
            'company_id': order_line.company_id.id,
            'customer_id': sale_order.partner_id.id,
            'description': order_line.name or order_line.product_id.name,
            'user_id': order_line.manager_id.id if hasattr(order_line, 'manager_id') else False,
            'allocated_hours': getattr(order_line, 'estimated_hours', 0.0),
            'active': True,
            'calculated_advance_amount': calculated_advance_amount,
            'date_start': order_line.engagement_start,
            'date': order_line.engagement_end,
            'auto_invoice': sale_order.auto_invoice,
            'budgeted_amount': advance_diff,
            'deadline': order_line.deadline,
            'billable_type': sale_order.billable_type 
        }

        project = Project.create(project_vals)
        new_stage = self.env.ref('project.project_stage_0')

        # --- Create tasks ---
        task_amount = advance_diff / order_line.product_uom_qty if order_line.product_uom_qty else 0.0
        estimated_hours = getattr(order_line, 'estimated_hours', 0.0)

        tasks_to_create = []
        for i in range(int(order_line.product_uom_qty)):
            task_name = f"Task {i + 1} for {order_line.product_id.name}"

            task_vals = {
                'name': task_name,
                'project_id': project.id,
                'sale_order_id': sale_order.id,
                'sale_line_id': order_line.id,
                'partner_id': sale_order.partner_id.id,
                'company_id': order_line.company_id.id,
                'user_ids': [(6, 0, [order_line.manager_id.id])] if order_line.manager_id else False,
                'description': order_line.name or order_line.product_id.name,
                'stage_id': new_stage.id,
                'auto_invoice': sale_order.auto_invoice,
                'allocated_hours': estimated_hours / order_line.product_uom_qty if order_line.product_uom_qty > 0 else 0.0,
                'task_budget': task_amount,
                'date_deadline': order_line.deadline,
                'billable_type':sale_order.billable_type
            }
            task = Task.create(task_vals)

            tasks_to_create.append(task_vals)

        order_line.write({'project_id': project.id})

        # Optional: Send notification
        if project.user_id and project.user_id.email:
            template = self.env.ref('project_extended_rk.project_creation_email_template', raise_if_not_found=False)
            if template:
                template.send_mail(project.id, force_send=True)
            else:
                project.user_id.partner_id.message_post(
                    subject=_("New Project Created"),
                    body=_("A new project '%s' has been created and assigned to you.") % project.name,
                    message_type="notification",
                    subtype_xmlid="mail.mt_comment"
                )

        return project

class AccountMove(models.Model):
    _inherit = 'account.move'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        compute='_compute_sale_order_line',
        inverse='_set_sale_order_line',  # make it editable
        store=True,
        # required=True
    )

    advance_invoice = fields.Boolean(
        string='Advance Amount',
        default=False
    )

    @api.depends('invoice_line_ids.sale_line_ids')
    def _compute_sale_order_line(self):
        for move in self:
            sale_lines = move.invoice_line_ids.mapped('sale_line_ids')
            move.sale_order_line_id = sale_lines[:1] if sale_lines else False

    def _set_sale_order_line(self):
        """This is called when user edits the field manually."""
        for move in self:
            if move.sale_order_line_id:
                # Optional: link the sale order line to first invoice line
                if move.invoice_line_ids:
                    move.invoice_line_ids[0].sale_line_ids = [(6, 0, [move.sale_order_line_id.id])]

