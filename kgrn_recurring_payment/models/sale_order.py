from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    is_recurring = fields.Boolean(
        string='Recurring Payment',
        default=False,
        tracking=True,
        help='Enable to link or create a recurring payment contract for this sale order.',
    )
    kgrn_recurring_contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Recurring Contract',
        copy=False,
        ondelete='set null',
        domain="[('customer_id', '=', partner_id)]",
        tracking=True,
    )
    kgrn_recurring_contract_state = fields.Selection(
        related='kgrn_recurring_contract_id.state',
        string='Contract Status',
        readonly=True,
    )
    kgrn_recurring_portal_url = fields.Char(
        related='kgrn_recurring_contract_id.portal_url',
        string='Payment Portal URL',
        readonly=True,
    )
    kgrn_recurring_payment_line_ids = fields.One2many(
        'kgrn.recurring.payment.line',
        'sale_order_id',
        string='Recurring Payments',
        readonly=True,
    )
    kgrn_recurring_payment_count = fields.Integer(
        string='Recurring Payments',
        compute='_compute_kgrn_recurring_payment_count',
    )
    kgrn_first_payment_done = fields.Boolean(
        string='First Payment Deducted',
        default=False,
        copy=False,
        help='Set to True once the first manual recurring payment has been triggered from the sale order.',
    )
    kgrn_recurring_locked = fields.Boolean(
        string='Recurring Toggle Locked',
        compute='_compute_kgrn_recurring_locked',
        help='True when the recurring toggle should be read-only (approval_state is past draft).',
    )

    def _get_kgrn_recurring_locked_depends(self):
        deps = ['state']
        if 'approval_state' in self._fields:
            deps.append('approval_state')
        return deps

    @api.depends(lambda self: self._get_kgrn_recurring_locked_depends())
    def _compute_kgrn_recurring_locked(self):
        has_approval = 'approval_state' in self._fields
        for order in self:
            if has_approval:
                order.kgrn_recurring_locked = order.approval_state != 'draft'
            else:
                order.kgrn_recurring_locked = order.state not in ('draft', 'sent')

    @api.depends('kgrn_recurring_payment_line_ids')
    def _compute_kgrn_recurring_payment_count(self):
        for order in self:
            order.kgrn_recurring_payment_count = len(order.kgrn_recurring_payment_line_ids)

    def action_recurring_first_payment(self):
        """Trigger the first recurring payment deduction directly from the sale order."""
        self.ensure_one()
        contract = self.kgrn_recurring_contract_id
        if not contract:
            raise UserError(_('No recurring contract is linked to this sale order.'))
        if contract.state != 'running':
            raise UserError(_('The recurring contract must be in Running state to deduct a payment.'))
        contract._process_single_payment()
        self.kgrn_first_payment_done = True

    def action_sale_send_portal_link(self):
        """Open the Send Portal Link wizard for the linked recurring contract."""
        self.ensure_one()
        contract = self.kgrn_recurring_contract_id
        if not contract:
            raise UserError(_('No recurring contract is linked to this sale order.'))
        return contract.action_send_portal_link()

    def action_create_recurring_contract(self):
        """Open a new recurring contract form pre-filled from this sale order."""
        self.ensure_one()
        if self.kgrn_recurring_contract_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Recurring Contract'),
                'res_model': 'kgrn.recurring.contract',
                'view_mode': 'form',
                'res_id': self.kgrn_recurring_contract_id.id,
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Recurring Contract'),
            'res_model': 'kgrn.recurring.contract',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_customer_id': self.partner_id.id,
                'default_currency_id': self.currency_id.id,
                'default_sale_order_id': self.id,
            },
        }
