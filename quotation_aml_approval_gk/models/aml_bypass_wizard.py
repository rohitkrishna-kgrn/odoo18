from odoo import models


class AmlBypassWizard(models.TransientModel):
    _inherit = 'aml.bypass.wizard'

    def action_save_bypass(self):
        order = self.sale_order_id
        if order and order._aml_restart_allowed():
            # The core wizard refuses when the latest request is closed.
            # Open a fresh (unsent) request for the restarted AML step so the
            # bypass closes that one; the cancelled request stays on record.
            order._check_aml_action_rights()
            self.env['aml.request'].sudo().create({
                'state': 'draft',
                'sale_order_id': order.id,
                'partner_id': order.partner_id.id,
                'kyc_type': order.kyc_type or 'entity',
                'company_id': order.company_id.id,
            })
        return super().action_save_bypass()
