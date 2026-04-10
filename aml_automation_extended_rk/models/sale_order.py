from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', tracking=True)

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

        # Pre-populate PI document lines
        pi_docs = [
            ('kyc_form', 10), ('trade_license', 20), ('branch_licenses', 30),
            ('cert_incorporation', 40), ('vat_corp_tax', 50), ('moa', 60),
            ('cert_incumbency', 70), ('shareholder_register', 80), ('director_register', 90),
            ('board_resolution', 100), ('share_certificates', 110), ('org_chart', 120),
            ('utility_bills', 130), ('lease_agreement', 140), ('business_profile', 150),
            ('authorized_signatories', 160), ('passport_individual', 170),
            ('emirates_id_individual', 180), ('family_book', 190), ('proof_of_residence', 200),
            ('corporate_shareholder_docs', 210), ('residing_together_declaration', 220),
            ('related_party_licenses', 230),
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
