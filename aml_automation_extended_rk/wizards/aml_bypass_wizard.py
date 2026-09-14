from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AmlBypassWizard(models.TransientModel):
    _name = 'aml.bypass.wizard'
    _description = 'AML/KYC Bypass Reason'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True, readonly=True)
    reason = fields.Text(string='Bypass Reason', required=True)

    def action_save_bypass(self):
        self.ensure_one()
        order = self.sale_order_id
        order._check_aml_action_rights()
        if order.sudo().aml_request_ids:
            raise UserError(_("An AML request already exists for this order."))
        if not (self.reason or '').strip():
            raise UserError(_("Enter a reason before saving the bypass."))

        aml = self.env['aml.request'].sudo().create({
            'state': 'bypassed',
            'sale_order_id': order.id,
            'partner_id': order.partner_id.id,
            'kyc_type': order.kyc_type or 'entity',
            'company_id': order.company_id.id,
        })

        acting_partner = self.env.user.partner_id
        highlighted_body = Markup(
            '<div style="background:#fff3e0;border-left:4px solid #f25d23;'
            'padding:10px 14px;border-radius:4px;margin:4px 0;">'
            '<p style="margin:0 0 4px;"><b>%s</b></p>'
            '<p style="margin:0;"><b>%s:</b> %s</p>'
            '</div>'
        ) % (
            _("AML/KYC Check Bypassed"),
            _("Reason"),
            self.reason,
        )
        order.sudo().message_post(body=highlighted_body, author_id=acting_partner.id)
        aml.sudo().message_post(body=highlighted_body, author_id=acting_partner.id)

        return {'type': 'ir.actions.act_window_close'}
