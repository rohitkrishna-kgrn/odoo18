from markupsafe import Markup

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AmlBypassWizard(models.TransientModel):
    _name = 'aml.bypass.wizard'
    _description = 'AML/KYC Bypass Reason'

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', required=True, readonly=True)
    reason = fields.Text(string='Bypass Reason', required=True)

    # Steers the warning banner: bypassing before any form was sent simply
    # skips sending it, but bypassing an existing (still open) request
    # immediately expires the KYC link already emailed to the client - the
    # portal routes in AmlPortalController only serve a request that is
    # still in one of sale.order._AML_OPEN_STATES.
    form_already_sent = fields.Boolean(compute='_compute_form_already_sent')

    @api.depends('sale_order_id')
    def _compute_form_already_sent(self):
        for wiz in self:
            wiz.form_already_sent = bool(wiz.sale_order_id.sudo().aml_request_ids)

    def action_save_bypass(self):
        self.ensure_one()
        order = self.sale_order_id
        order._check_aml_action_rights()
        if not (self.reason or '').strip():
            raise UserError(_("Enter a reason before saving the bypass."))

        existing = order.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]
        if existing and existing.state not in order._AML_OPEN_STATES:
            raise UserError(_(
                "This order's AML/KYC check has already reached a final "
                "outcome and can no longer be bypassed."
            ))

        if existing:
            # Close out the existing request instead of creating a second
            # one - this also expires its KYC (and, if applicable,
            # additional-info) portal links immediately, since those routes
            # only serve a request still in an open state.
            aml = existing
            aml.sudo().write({'state': 'bypassed'})
        else:
            aml = self.env['aml.request'].sudo().create({
                'state': 'bypassed',
                'sale_order_id': order.id,
                'partner_id': order.partner_id.id,
                'kyc_type': order.kyc_type or 'entity',
                'company_id': order.company_id.id,
            })

        acting_partner = self.env.user.partner_id
        expiry_note = Markup('<p style="margin:4px 0 0;">%s</p>') % _(
            "The KYC form link already sent to the client is now expired."
        ) if existing else Markup('')
        highlighted_body = Markup(
            '<div style="background:#fff3e0;border-left:4px solid #f25d23;'
            'padding:10px 14px;border-radius:4px;margin:4px 0;">'
            '<p style="margin:0 0 4px;"><b>%s</b></p>'
            '<p style="margin:0;"><b>%s:</b> %s</p>'
            '%s'
            '</div>'
        ) % (
            _("AML/KYC Check Bypassed"),
            _("Reason"),
            self.reason,
            expiry_note,
        )
        order.sudo().message_post(body=highlighted_body, author_id=acting_partner.id)
        aml.sudo().message_post(body=highlighted_body, author_id=acting_partner.id)

        # _check_aml_action_rights() above already limited this action to
        # the AML team or the Quotation Approver - so "not AML team" here
        # means the approver is the one who just overrode the gate, and
        # only the AML Manager needs to be alerted with the reason (the AML
        # team bypassing its own pipeline needs no extra email).
        if not self.env.user.has_group('aml_automation_extended_rk.group_aml_user'):
            aml.sudo()._notify_aml_managers_bypass_by_approver(self.reason)

        return {'type': 'ir.actions.act_window_close'}
