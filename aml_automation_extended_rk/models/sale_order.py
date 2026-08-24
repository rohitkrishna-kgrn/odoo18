from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # States on aml.request that count as the responsible person having
    # marked AML/KYC "Completed": either a full approval, or a manager
    # bypass (AML determined not required for this client).
    _AML_GATE_COMPLETED_STATES = ('approved', 'bypassed')

    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', tracking=True, required=True)

    aml_request_ids = fields.One2many('aml.request', 'sale_order_id', string='AML Requests')
    aml_request_count = fields.Integer(compute='_compute_aml_request_count', string='AML Requests')

    aml_gate_completed = fields.Boolean(
        string='AML/KYC Completed', compute='_compute_aml_gate_completed',
    )

    aml_gate_override = fields.Boolean(
        string='Override AML Gate', copy=False, tracking=True,
        help="Allows project creation before AML/KYC is marked Completed. "
             "Restricted to Administrators; requires a reason.",
    )
    aml_gate_override_reason = fields.Text(string='AML Gate Override Reason', copy=False, tracking=True)
    aml_gate_override_by = fields.Many2one('res.users', string='AML Gate Overridden By', readonly=True, copy=False)
    aml_gate_override_date = fields.Datetime(string='AML Gate Overridden On', readonly=True, copy=False)

    _AML_GATE_OVERRIDE_FIELDS = {'aml_gate_override', 'aml_gate_override_reason'}

    # Both computes run for anyone opening a sale order, including salespeople
    # with no AML group. They read through sudo so the AML records stay
    # restricted while the gate status itself remains visible on the quotation.
    @api.depends('aml_request_ids')
    def _compute_aml_request_count(self):
        for order in self:
            order.aml_request_count = len(order.sudo().aml_request_ids)

    @api.depends('aml_request_ids.state')
    def _compute_aml_gate_completed(self):
        for order in self:
            latest = order.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]
            order.aml_gate_completed = bool(latest) and latest.state in self._AML_GATE_COMPLETED_STATES

    def _check_aml_gate(self):
        """Block project creation for this order's engagement until AML/KYC
        is Completed (Approved or Bypassed), unless an Administrator has
        recorded an override with a reason."""
        for order in self:
            if order.aml_gate_completed or order.aml_gate_override:
                continue
            raise UserError(_(
                "Cannot create a project for '%s': AML/KYC has not been marked Completed "
                "for this client yet. An Administrator can record an exception under "
                "'AML Gate Override' on the sale order if one is needed."
            ) % order.name)

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
                ('lease_agreement', 100), ('business_profile', 110),
                ('authorized_signatories', 120), ('family_book', 130),
                ('residing_together_declaration', 140),
                ('related_party_licenses', 150),
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
        if self._AML_GATE_OVERRIDE_FIELDS.intersection(vals):
            if not self.env.user.has_group('base.group_system'):
                raise UserError(_("Only Administrators can override the AML/KYC completion gate."))
            if vals.get('aml_gate_override'):
                has_reason = vals.get('aml_gate_override_reason') or any(
                    order.aml_gate_override_reason for order in self
                )
                if not has_reason:
                    raise UserError(_("Enter a reason before overriding the AML/KYC gate."))
                vals = dict(vals)
                vals['aml_gate_override_by'] = self.env.user.id
                vals['aml_gate_override_date'] = fields.Datetime.now()

        if vals.get('state') == 'cancel':
            cancellable_states = ('draft', 'new', 'accepted', 'in_progress',
                                  'hit_detected', 'additional_info', 'no_hit')
            for order in self:
                # Cancelling a quotation must not require AML rights.
                aml_to_cancel = order.sudo().aml_request_ids.filtered(
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
