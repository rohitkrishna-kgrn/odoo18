from odoo import api, models, fields, _
from odoo.exceptions import UserError, ValidationError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    reminder_date = fields.Date(string='Reminder Date')
    advance_amount = fields.Float(string='Advance Amount', default=0.00)
    auto_invoice = fields.Boolean(string="Auto Invoice", default=True)

    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')
    pending_amount = fields.Monetary(string='Pending Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')

    order_status = fields.Selection(
        [
            ('new', 'New'),
            ('opened', 'Opened'),
            ('closed', 'Closed'),
        ],
        string='Order Status',
        default='new',
        required=True,
    )

    # eInvoicing engagement info (mirrors the opportunity)
    opportunity_einvoicing = fields.Boolean(
        string='Opportunity eInvoicing', compute='_compute_opportunity_einvoicing')
    einvoicing_service = fields.Boolean(
        string='eInvoicing Service', compute='_compute_einvoicing_service',
        store=True, readonly=False,
        help="Automatically enabled (and locked) when the linked opportunity is an "
             "eInvoicing Service opportunity.")
    entity_count = fields.Integer(string='Number of Entities')

    @api.depends('opportunity_id.discovery_form_type')
    def _compute_opportunity_einvoicing(self):
        for order in self:
            order.opportunity_einvoicing = order.opportunity_id.discovery_form_type == 'einvoicing'

    @api.depends('opportunity_id.discovery_form_type')
    def _compute_einvoicing_service(self):
        for order in self:
            # Forced on when the opportunity is an eInvoicing one; otherwise the
            # value stays whatever it already was (manually set).
            order.einvoicing_service = bool(
                order.einvoicing_service or order.opportunity_id.discovery_form_type == 'einvoicing')

    posted_invoice_total = fields.Monetary(
        string="Posted Invoice Total",
        compute="_compute_posted_invoice_total",
        currency_field='currency_id',
    )

    @api.depends('invoice_ids.amount_total', 'invoice_ids.state')
    def _compute_posted_invoice_total(self):
        for order in self:
            total = 0.0
            for inv in order.invoice_ids:
                if inv.state == 'posted':
                    total += inv.amount_total
            order.posted_invoice_total = total

    def action_open_invoice_wizard(self):
        return {
            'name': 'Create Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            }
        }

    @api.depends('invoice_ids.payment_state', 'amount_total')
    def _compute_paid_pending(self):
        for order in self:
            paid = 0.0
            # Calculate paid amount from invoices
            invoices = order.invoice_ids.filtered(lambda inv: inv.state in ['posted', 'paid'])
            for inv in invoices:
                # inv.amount_residual is unpaid amount, so paid is total - residual
                paid += inv.amount_total - inv.amount_residual

            order.paid_amount = paid
            order.pending_amount = order.amount_total - paid

    # ------------------------------------------------------------------
    # Pipeline stage automation driven by the linked opportunity
    # ------------------------------------------------------------------
    def _set_opportunity_stage(self, stage_xmlid):
        """Move each linked opportunity to the stage given by external id."""
        stage = self.env.ref(stage_xmlid, raise_if_not_found=False)
        if not stage:
            return
        opportunities = self.mapped('opportunity_id').filtered(
            lambda lead: lead.stage_id != stage)
        if opportunities:
            opportunities.write({'stage_id': stage.id})

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        proposition = self.env.ref('crm.stage_lead3', raise_if_not_found=False)
        for order in orders:
            lead = order.opportunity_id
            if not lead:
                continue
            # Link the created sale order back onto the pipeline record.
            lead.sale_order_id = order.id
            # A new draft quotation moves its opportunity forward to "Proposition"
            # (only from an earlier stage - never drags it back).
            if (proposition and order.state == 'draft'
                    and lead.stage_id.sequence < proposition.sequence):
                lead.stage_id = proposition.id
        return orders

    @api.constrains('approval_state', 'tag_ids')
    def _check_tag_required_before_approval(self):
        for order in self:
            if order.approval_state != 'draft' and not order.tag_ids:
                raise ValidationError(_(
                    "Please select a Tag (Other Info > Sales) before this "
                    "quotation can leave Draft."))

    def action_submit_for_approval(self):
        for order in self:
            if not order.tag_ids:
                raise UserError(_(
                    "Please select a Tag (Other Info > Sales) before "
                    "submitting this quotation for approval."))
        return super().action_submit_for_approval()

    def action_approve_order(self):
        res = super().action_approve_order()
        # Approved quotation -> opportunity moves to "Service Engagement".
        self.filtered(lambda o: o.approval_state == 'approved')._set_opportunity_stage(
            'crm_extended_rk.stage_service_engagement')
        return res

    def action_confirm(self):
        res = super().action_confirm()
        # Confirmed order -> opportunity moves to "Won".
        self._set_opportunity_stage('crm.stage_lead4')
        return res

    def action_cancel(self):
        res = super().action_cancel()
        # Cancelled order -> opportunity moves to "Lost".
        self._set_opportunity_stage('crm_extended_rk.stage_lost')
        return res

    # def _create_advance_invoice(self):
    #     self.ensure_one()

    #     if not self.partner_invoice_id:
    #         raise UserError("Please set an invoice address for the customer.")

    #     existing_invoice = self.invoice_ids.filtered(
    #         lambda inv: inv.state == 'draft' and
    #                     inv.amount_total == self.advance_amount and
    #                     inv.invoice_origin == self.name
    #     )
    #     if existing_invoice:
    #         return

    #     income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
    #     if not income_account:
    #         raise UserError("No income account found for advance invoice line.")

    #     # Optionally reference the first order line (if you want to link it)
    #     sale_line = self.order_line[:1]  # You can also create a fake "advance" line if needed

    #     invoice_vals = {
    #         'move_type': 'out_invoice',
    #         'partner_id': self.partner_invoice_id.id,
    #         'invoice_origin': self.name,
    #         'invoice_user_id': self.user_id.id,
    #         'currency_id': self.currency_id.id,
    #         'invoice_payment_term_id': self.payment_term_id.id,
    #         'invoice_line_ids': [(0, 0, {
    #             'name': 'Advance Payment',
    #             'quantity': 1,
    #             'price_unit': self.advance_amount,
    #             'account_id': income_account.id,
    #             'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
    #             # ✅ Link to Sale Order Line (for reporting)
    #             'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
    #         })],
    #     }

    #     invoice = self.env['account.move'].create(invoice_vals)
    #     return invoice


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    engagement_start = fields.Date(string='Engagement Start', required=True)
    engagement_end = fields.Date(string='Engagement End', required=True)
    manager_id = fields.Many2one('res.users', string='Manager', required=True)
    deadline = fields.Date(string='Deadline', required=True)
    estimated_hours = fields.Float(string='Estimated Number of Hours', required=True)

    @api.onchange('product_id')
    def _onchange_product_id_fetch_estimated_hours(self):
        if self.product_id:
            self.estimated_hours = self.product_id.product_tmpl_id.estimated_hours  # get from product template

    @api.onchange('manager_id')
    def _onchange_manager_id_dedicated_check(self):
        if self.manager_id and not self.manager_id.is_dedicated_manager:
            self.manager_id = False
            return {
                'warning': {
                    'title': _("Invalid Manager"),
                    'message': _(
                        "Only users designated as Dedicated Project Managers can be "
                        "assigned as the Manager for this quotation line. Please select "
                        "a user with the Dedicated Project Manager permission enabled."
                    ),
                }
            }

    @api.constrains('manager_id')
    def _check_manager_is_dedicated(self):
        for line in self:
            if line.manager_id and not line.manager_id.is_dedicated_manager:
                raise ValidationError(_(
                    "Only users designated as Dedicated Project Managers can be "
                    "assigned as the Manager for this quotation line. Please select "
                    "a user with the Dedicated Project Manager permission enabled."
                ))


class ResUsers(models.Model):
    _inherit = 'res.users'

    is_dedicated_manager = fields.Boolean(string='Dedicated Project Manager', default=False)

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    estimated_hours = fields.Float(string='Estimated Hours')

class ProjectProject(models.Model):
    _inherit = 'project.project'

    estimated_hours = fields.Float(string='Estimated Hours')
