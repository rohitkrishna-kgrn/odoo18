from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_referral_lead_id = fields.Many2one(
        'crm.lead',
        string='Referral Lead',
        ondelete='set null',
        index=True,
    )

    # Quotations are raised from the lead with the standard CRM "New
    # Quotation" button (or the CRM Pipeline field), and crm_extended_rk moves
    # the lead through Proposition / Service Engagement / Won / Lost. This only
    # keeps the referral's own order link (deal value, commission) in step.

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            lead = order.opportunity_id
            if lead.x_is_referral:
                order.sudo().x_referral_lead_id = lead.id
                if not lead.x_sale_order_id:
                    lead.sudo().x_sale_order_id = order.id
        return orders

    def action_confirm(self):
        res = super().action_confirm()
        # The confirmed order is the deal the commission is earned on, even
        # when the lead carried other (cancelled or older) quotations.
        for order in self:
            lead = order.x_referral_lead_id or order.opportunity_id
            if lead.x_is_referral and lead.x_sale_order_id != order:
                lead.sudo().x_sale_order_id = order.id
                order.sudo().x_referral_lead_id = lead.id
        return res


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        # Covers both invoicing routes: sale.order._create_invoices and the
        # Services "Create Invoice" wizard, which builds the move itself.
        moves = super().create(vals_list)
        for move in moves.filtered(lambda m: m.move_type == 'out_invoice'):
            orders = move.sudo().invoice_line_ids.sale_line_ids.order_id
            for lead in orders.x_referral_lead_id:
                if lead.x_is_referral and not lead.x_invoice_id:
                    lead.x_invoice_id = move.id
        return moves
