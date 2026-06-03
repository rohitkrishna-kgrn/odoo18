from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', tracking=True, required=True)

    aml_request_ids = fields.One2many('aml.request', 'sale_order_id', string='AML Requests')
    aml_request_count = fields.Integer(compute='_compute_aml_request_count', string='AML Requests')

    @api.depends('aml_request_ids')
    def _compute_aml_request_count(self):
        for order in self:
            order.aml_request_count = len(order.aml_request_ids)

    def action_approve_order(self):
        """Override: after approval send KYC form to client."""
        result = super().action_approve_order()
        for order in self:
            if order.partner_id and order.partner_id.email:
                order._create_aml_request_and_send_form()
        return result

    def _create_aml_request_and_send_form(self):
        self.ensure_one()
        # Create draft AML request
        aml = self.env['aml.request'].sudo().create({
            'state': 'draft',
            'sale_order_id': self.id,
            'partner_id': self.partner_id.id,
            'kyc_type': self.kyc_type or 'entity',
            'company_id': self.company_id.id,
        })
        aml._portal_ensure_token()

        # Pre-populate PI document lines based on KYC type
        if aml.kyc_type == 'individual':
            pi_docs = [
                ('ind_passport_copy', 10),
                ('ind_proof_residence', 20),
                ('ind_visa', 30),
                ('ind_emirates_id_doc', 40),
                ('ind_profile_cv', 50),
            ]
        else:
            pi_docs = [
                ('trade_license', 10), ('branch_licenses', 20),
                ('cert_incorporation', 30), ('vat_corp_tax', 40), ('moa', 50),
                ('cert_incumbency', 60),
                ('board_resolution', 70), ('share_certificates', 80), ('org_chart', 90),
                ('utility_bills', 100), ('lease_agreement', 110), ('business_profile', 120),
                ('authorized_signatories', 130), ('family_book', 140),
                ('residing_together_declaration', 150),
                ('related_party_licenses', 160),
            ]
        for doc_key, seq in pi_docs:
            self.env['aml.request.document'].sudo().create({
                'request_id': aml.id,
                'doc_key': doc_key,
                'sequence': seq,
            })

        # Send branded KYC email directly (avoids Jinja2 template rendering issues in Odoo 18)
        aml._send_kyc_form_email()
        return aml

    def write(self, vals):
        if vals.get('state') == 'cancel':
            cancellable_states = ('draft', 'new', 'accepted', 'in_progress',
                                  'hit_detected', 'additional_info', 'no_hit')
            for order in self:
                aml_to_cancel = order.aml_request_ids.filtered(
                    lambda r: r.state in cancellable_states
                )
                if aml_to_cancel:
                    aml_to_cancel.sudo().write({'state': 'cancelled'})
                    for aml in aml_to_cancel:
                        aml.sudo().message_post(
                            body=_("Request automatically cancelled because Sale Order %s was cancelled.")
                                 % order.name
                        )
        return super().write(vals)

    def action_view_aml_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('AML Requests'),
            'res_model': 'aml.request',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }
