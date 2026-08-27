from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
    ], string="Approval Status", default="draft", tracking=True)

    is_user_approver = fields.Boolean(compute="_compute_is_user_approver")

    is_locked = fields.Boolean(compute="_compute_is_locked", store=True)

    @api.depends('approval_state')
    def _compute_is_locked(self):
        for order in self:
            order.is_locked = order.approval_state == 'approved'

    @api.depends('company_id.approver_user_id')
    def _compute_is_user_approver(self):
        for order in self:
            order.is_user_approver = (order.company_id.approver_user_id == self.env.user)

    def action_submit_for_approval(self):
        for order in self:
            if order.state != 'draft':
                raise UserError(_("Only draft quotations can be submitted for approval."))
            if not order.company_id.approver_user_id:
                raise UserError(_("No approver set in the company."))
            order.approval_state = 'to_approve'

            order.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=order.company_id.approver_user_id.id,
                note=_("Quotation %s needs your approval.") % order.name,
                summary=_("Approval Request")
            )
            approver = order.company_id.approver_user_id.sudo()
            if approver.email:
                mail_values = {
                    'subject': _("Approval Required: Quotation %s") % order.name,
                    'body_html': """
                        <p>Dear {approver_name},</p>
                        <p>The quotation <strong>{order_name}</strong> has been submitted for your approval.</p>
                        <p><strong>Customer:</strong> {customer_name}<br/>
                           <strong>Amount Total:</strong> {amount} {currency}<br/>
                           <strong>Submitted By:</strong> {user}</p>
                        <p>You can review it in the system.</p>
                        <p>Thank you.</p>
                    """.format(
                        approver_name=approver.name,
                        order_name=order.name,
                        customer_name=order.partner_id.name,
                        amount=order.amount_total,
                        currency=order.currency_id.name,
                        user=self.env.user.name
                    ),
                    'email_to': approver.email,
                    'author_id': self.env.user.partner_id.id,
                    'model': 'sale.order',
                    'res_id': order.id,
                }

                self.env['mail.mail'].sudo().create(mail_values).send()

    def action_confirm(self):
        self.ensure_one()
        from_einvoicing = self.env.context.get('einvoicing_portal', False)
        if not from_einvoicing:
            if self.approval_state != 'approved' and self.env.user != self.company_id.approver_user_id:
                raise UserError(_("Only the approver can confirm this order before approval."))
            if self.approval_state != 'approved':
                raise UserError(_("Order must be in 'Approved' state to confirm."))

        return super(SaleOrder, self).action_confirm()

    def action_cancel(self):
        self.ensure_one()
        if self.env.user != self.company_id.approver_user_id:
            raise UserError(_("Only the designated approver can cancel the order."))
        return super(SaleOrder, self).action_cancel()


    def action_approve_order(self):
        self.ensure_one()
        from_einvoicing = self.env.context.get('einvoicing_portal', False)
        if not from_einvoicing:
            if self.approval_state != 'to_approve':
                raise UserError(_("Only quotations in 'To Approve' state can be approved."))
            if self.env.user != self.company_id.approver_user_id:
                raise UserError(_("Only the designated approver can approve this quotation."))

        import re
        original_name = self.name or ''

        # Try to keep the numeric part but replace prefix S -> SE
        match = re.match(r'S(\d+)', original_name)
        if match:
            number_part = match.group(1)
            self.name = f'SE{number_part}'
        else:
            # fallback: generate new number from custom sequence
            seq = self.env['ir.sequence'].sudo().search([('code', '=', 'sale.order.se_sequence')], limit=1)
            if not seq:
                seq = self.env['ir.sequence'].sudo().create({
                    'name': 'Sale Order SE Sequence',
                    'code': 'sale.order.se_sequence',
                    'prefix': 'SE',
                    'padding': 5,
                    'implementation': 'standard',
                })
            self.name = seq.next_by_id()
        
        if self.advance_amount > 0.0:
            self._create_advance_invoice()
        
        self.approval_state = 'approved'
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'sale.order'),
            ('res_id', '=', self.id),
            ('user_id', '=', self.env.user.id),
            ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
        ])

        for activity in activities:
            activity.action_feedback(_("Approved by %s") % self.env.user.name)

class ResUsers(models.Model):
    _inherit = 'res.users'

    can_manage_products = fields.Boolean(
        string='Create / Edit Products',
        help="Allows this user to create and modify products. Without it, saving "
             "a product raises an error — regardless of the user's other rights.")


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _check_product_management_rights(self, action):
        """Product maintenance is granted per user, not by being an administrator.

        Module data loading is exempt so installs and upgrades can still ship
        products of their own.
        """
        if self.env.su or self.env.context.get('install_module'):
            return
        if not self.env.user.can_manage_products:
            raise UserError(_(
                "You are not allowed to %s products.\n\n"
                "Ask an administrator to tick 'Create / Edit Products' on your "
                "user record (Settings > Users > Access Rights).",
                action))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_product_management_rights(_("create"))
        return super().create(vals_list)

    def write(self, vals):
        self._check_product_management_rights(_("modify"))
        return super().write(vals)
