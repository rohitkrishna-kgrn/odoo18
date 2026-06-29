from odoo import api, fields, models

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_referral_lead_id = fields.Many2one(
        'crm.lead',
        string='Referral Lead',
        ondelete='set null',
        index=True,
    )

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for order in self:
            lead = order.x_referral_lead_id
            if not lead or not lead.x_is_referral or lead.x_invoice_id:
                continue
            invoices = order.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
            if invoices:
                lead.sudo().x_invoice_id = invoices[0].id
        return moves

    def action_approve_order(self):
        res = super().action_approve_order()
        for order in self:
            lead = order.x_referral_lead_id
            if not lead or not lead.x_is_referral:
                continue
            qualified = self.env['crm.stage'].search(
                [('x_is_referral_stage', '=', True), ('x_is_referral_converted', '=', False),
                 ('x_is_referral_lost', '=', False), ('name', 'ilike', 'Qualified')],
                order='sequence', limit=1,
            )
            if not qualified:
                qualified = self.env['crm.stage'].search(
                    [('x_is_referral_stage', '=', True), ('x_is_referral_converted', '=', False),
                     ('x_is_referral_lost', '=', False)],
                    order='sequence desc', limit=1,
                )
                # find the one just before Converted
                stages = self.env['crm.stage'].search(
                    [('x_is_referral_stage', '=', True)], order='sequence')
                converted = stages.filtered('x_is_referral_converted')
                if converted:
                    idx = list(stages.ids).index(converted[0].id)
                    if idx > 0:
                        qualified = stages[idx - 1]
            if qualified:
                lead.stage_id = qualified.id
            # Sync revenue from SO
            lead.expected_revenue = order.amount_total
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            lead = order.x_referral_lead_id
            if not lead or not lead.x_is_referral:
                continue
            converted = self.env['crm.stage'].search(
                [('x_is_referral_stage', '=', True), ('x_is_referral_converted', '=', True)],
                order='sequence', limit=1,
            )
            if converted:
                lead.stage_id = converted.id
        return res
