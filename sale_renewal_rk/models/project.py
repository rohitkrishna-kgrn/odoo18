from odoo import models, fields, api
from odoo.exceptions import UserError

class ProjectProject(models.Model):
    _inherit = "project.project"

    def action_renew_sale_order(self):
        self.ensure_one()

        if self.stage_id.name.lower() == 'todo':
            raise UserError(
                "Project must be in 'In Progress' or 'Done' stage to renew."
            )

        # Fetch tasks linked to sale lines
        tasks = self.env['project.task'].sudo().search([
            ('project_id', '=', self.id),
            ('sale_line_id', '!=', False),
        ])

        if not tasks:
            raise UserError(
                "No project tasks are linked to a Sale Order line."
            )

        # Done tasks only
        done_tasks = tasks.filtered(
            lambda t: t.stage_id.name.lower() == 'done'
        )

        if not done_tasks:
            raise UserError(
                "No completed (Done) tasks found to renew."
            )

        # Determine renewal type
        renewal_state = (
            'renewed'
            if len(done_tasks) == len(tasks)
            else 'partially_renewed'
        )

        # Use the first done task to locate sale order
        sale_line = done_tasks[0].sale_line_id.sudo()
        old_so = sale_line.order_id.sudo()

        if not old_so:
            raise UserError("Original Sale Order not found.")

        order_lines = []

        for line in old_so.order_line:
            order_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                # ✅ Qty = count of Done tasks ONLY
                'product_uom_qty': len(done_tasks),
                'price_unit': line.price_unit,
                'tax_id': [(6, 0, line.tax_id.ids)],
                'manager_id': getattr(line, 'manager_id', False) and line.manager_id.id,
                'engagement_start': getattr(line, 'engagement_start', False),
                'engagement_end': getattr(line, 'engagement_end', False),
                'estimated_hours': getattr(line, 'estimated_hours', False),
                'deadline': getattr(line, 'deadline', False),
            }))

        new_so = self.env['sale.order'].with_context(
            from_project_renewal=True,
            renewal_state=renewal_state
        ).sudo().create({
            'partner_id': old_so.partner_id.id,
            'order_line': order_lines,
            'state': 'draft',
            'new_renewed': 'renewed'
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': new_so.id,
        }

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    new_renewed = fields.Selection(
        [
            ('new', 'New'),
            ('renewed', 'Renewed'),
            ('partially_renewed', 'Partially Renewed'),
        ],
        string="New / Renewed",
        default='new'
    )

    # @api.model
    # def create(self, vals):
    #     if not self.env.context.get('from_project_renewal'):
    #         if not self.env.user.sales_team:
    #             raise UserError(
    #                 "Only Sales Team members can create Sale Orders."
    #             )

    #     if self.env.context.get('from_project_renewal'):
    #         vals['new_renewed'] = self.env.context.get(
    #             'renewal_state', 'renewed'
    #         )
    #     else:
    #         vals.setdefault('new_renewed', 'new')

    #     return super().create(vals)

    @api.model
    def create(self, vals):
        # Set default if not provided
        vals.setdefault('new_renewed', 'new')

        # Permission check: only Sales Team can create 'new' sale orders
        if vals.get('new_renewed') == 'new' and not self.env.user.sales_team:
            raise UserError("Only Sales Team members can create Sale Orders in 'New' stage.")

        return super().create(vals)