from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # States on aml.request that count as the responsible person having
    # marked AML/KYC "Completed": either a full approval, or a manager
    # bypass (AML determined not required for this client).
    _AML_GATE_COMPLETED_STATES = ('approved', 'bypassed')

    # Asked for only while a quotation is being created (the form view makes
    # it required on unsaved records). Existing quotations - including the
    # thousands that pre-date this module - stay editable without it.
    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', tracking=True)

    aml_request_ids = fields.One2many('aml.request', 'sale_order_id', string='AML Requests')
    aml_request_count = fields.Integer(compute='_compute_aml_request_count', string='AML Requests')

    # Stored (not just computed) so the "Pending AML" search filter can run
    # a plain domain against it; a non-stored field can't be searched. An
    # override counts as Completed - project creation reads only this flag.
    aml_gate_completed = fields.Boolean(
        string='AML/KYC Completed', compute='_compute_aml_gate_completed',
        store=True,
    )

    # Display counterpart of aml_gate_completed: distinguishes a real AML
    # approval from an override, which aml_gate_completed alone can't.
    aml_gate_status = fields.Selection([
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('overridden', 'Overridden'),
    ], string='AML/KYC Status', compute='_compute_aml_gate_completed', store=True)

    # Technical flag driving the visibility of the override tab. The override
    # is limited to the company's designated Quotation Approver. Everyone
    # else never sees the tab and is refused in write() even if they reach
    # the field another way.
    aml_gate_override_allowed = fields.Boolean(
        string='Can Override AML Gate',
        compute='_compute_aml_gate_override_allowed',
    )

    aml_gate_override = fields.Boolean(
        string='Override AML Gate', copy=False, tracking=True,
        help="Allows project creation before AML/KYC is marked Completed. "
             "Restricted to the designated Quotation Approver; requires a "
             "reason.",
    )
    aml_gate_override_reason = fields.Text(string='AML Gate Override Reason', copy=False, tracking=True)
    aml_gate_override_by = fields.Many2one('res.users', string='AML Gate Overridden By', readonly=True, copy=False)
    aml_gate_override_date = fields.Datetime(string='AML Gate Overridden On', readonly=True, copy=False)

    _AML_GATE_OVERRIDE_FIELDS = {'aml_gate_override', 'aml_gate_override_reason'}

    # Same set action_cancel's cascade below uses - any request still sitting
    # in an open pipeline stage when the gate is overridden.
    _AML_GATE_OVERRIDE_BYPASSABLE_STATES = (
        'draft', 'new', 'accepted', 'in_progress',
        'hit_detected', 'additional_info', 'no_hit',
    )

    # Both computes run for anyone opening a sale order, including salespeople
    # with no AML group. They read through sudo so the AML records stay
    # restricted while the gate status itself remains visible on the quotation.
    @api.depends('aml_request_ids')
    def _compute_aml_request_count(self):
        for order in self:
            order.aml_request_count = len(order.sudo().aml_request_ids)

    @api.depends('aml_request_ids.state', 'aml_gate_override')
    def _compute_aml_gate_completed(self):
        for order in self:
            latest = order.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]
            request_completed = bool(latest) and latest.state in self._AML_GATE_COMPLETED_STATES
            order.aml_gate_completed = request_completed or order.aml_gate_override
            if order.aml_gate_override:
                order.aml_gate_status = 'overridden'
            elif request_completed:
                order.aml_gate_status = 'completed'
            else:
                order.aml_gate_status = 'pending'

    @api.depends('company_id')
    @api.depends_context('uid')
    def _compute_aml_gate_override_allowed(self):
        user = self.env.user
        for order in self:
            order.aml_gate_override_allowed = order.company_id.approver_user_id == user

    # Drives visibility of the "Send AML Form" / "AML Bypass" buttons shown
    # once the order is Approved. Deliberately not a res.groups check alone -
    # the Quotation Approver is a single per-company user, not a group.
    aml_action_allowed = fields.Boolean(
        string='Can Send/Bypass AML Form',
        compute='_compute_aml_action_allowed',
    )

    @api.depends('company_id')
    @api.depends_context('uid')
    def _compute_aml_action_allowed(self):
        user = self.env.user
        is_aml_team = user.has_group('aml_automation_extended_rk.group_aml_user')
        for order in self:
            order.aml_action_allowed = is_aml_team or order.company_id.approver_user_id == user

    def _check_aml_action_rights(self):
        """Guard for action_send_aml_form / action_open_aml_bypass_wizard: limited
        to the AML team (group_aml_user, implied by group_aml_manager) or the
        order's designated Quotation Approver."""
        self.ensure_one()
        if self.env.su:
            return
        user = self.env.user
        is_aml_team = user.has_group('aml_automation_extended_rk.group_aml_user')
        if not is_aml_team and self.company_id.approver_user_id != user:
            raise UserError(_(
                "Only the AML Manager, AML User, or the designated Quotation Approver "
                "can send the AML form or bypass the AML/KYC check."
            ))

    def action_approve_order(self):
        """Override: after approval, alert the AML team the order is waiting on
        them to either send the AML/KYC form or record a bypass - sending the
        form to the client itself is now a deliberate button click, not
        automatic."""
        result = super().action_approve_order()
        for order in self:
            order._notify_aml_team_order_approved()
        return result

    def _notify_aml_team_order_approved(self):
        """Email the AML team (Manager + User - manager already carries User
        via implied_ids, so one group search reaches both) that this order is
        Approved and awaiting the Send AML Form / AML Bypass choice, with a
        direct link back to the order's backend form."""
        self.ensure_one()
        user_group = self.env.ref('aml_automation_extended_rk.group_aml_user')
        aml_team = self.env['res.users'].sudo().search([
            ('groups_id', 'in', user_group.ids), ('active', '=', True),
        ])
        emails = {u.email for u in aml_team if u.email}
        if not emails:
            return

        order_url = '%s/web#id=%s&model=sale.order&view_type=form' % (self.get_base_url(), self.id)
        # aml.request owns the branded email look (shell/CTA button/mail-from);
        # .new() reuses those instance methods without persisting a row.
        helper = self.env['aml.request'].new({'company_id': self.company_id.id})
        cta_button = helper._email_cta_button(_('Open %s') % self.name, order_url)
        body_html = """
        <p style="color:%(navy)s;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;margin:0 0 16px;">
          Quotation <strong>%(order)s</strong> has been approved. Please check the AML/KYC step -
          either send the AML/KYC form to the client, or record a bypass with a reason,
          from the sale order.
        </p>
        %(cta_button)s""" % {
            'navy': helper._EMAIL_NAVY,
            'order': self.name,
            'cta_button': cta_button,
        }
        full_body = helper._email_shell(
            title=_('Quotation Approved - AML/KYC Action Needed'),
            subtitle=self.name,
            body_html=body_html,
        )
        email_from = helper._get_mail_from()
        for email in emails:
            self.env['mail.mail'].sudo().create({
                'subject': _("Quotation %s Approved - AML/KYC Action Needed") % self.name,
                'body_html': full_body,
                'email_from': email_from,
                'email_to': email,
                'author_id': self.env.user.partner_id.id,
                'model': 'sale.order',
                'res_id': self.id,
            }).send()

    def _check_aml_gate_override_rights(self):
        """Guard for write() on the override fields. The override is limited
        to each order's designated Quotation Approver - anyone else is
        refused even if they can otherwise edit the order."""
        if self.env.su:
            return
        outsiders = self.filtered(
            lambda o: o.company_id.approver_user_id != self.env.user
        )
        if outsiders:
            raise UserError(_(
                "Only the designated Quotation Approver can override the "
                "AML/KYC completion gate."
            ))

    def _check_aml_gate(self, action_label=None):
        """Block a downstream action for this order's engagement until AML/KYC
        is Completed (Approved or Bypassed), unless the Quotation Approver has
        recorded an override with a reason. ``action_label`` names the blocked
        action in the error message (defaults to the original project-creation
        caller's wording)."""
        action_label = action_label or _("create a project")
        for order in self:
            if order.aml_gate_completed:
                continue
            raise UserError(_(
                "Cannot %s for '%s': AML/KYC has not been marked Completed "
                "for this client yet. The Quotation Approver can record an exception "
                "under 'AML Gate Override' on the sale order if one is needed."
            ) % (action_label, order.name))

    def action_send_aml_form(self):
        """Manual counterpart of the old auto-send: create the AML request and
        email the KYC form to the client. Restricted to the AML team / the
        Quotation Approver, and only while no AML request exists yet for
        this order (the button hides itself once one does)."""
        self.ensure_one()
        self._check_aml_action_rights()
        if self.sudo().aml_request_ids:
            raise UserError(_("An AML request already exists for this order."))
        if not self.partner_id.email:
            raise UserError(_(
                "%s does not have an email address on file. Add one before "
                "sending the AML form."
            ) % self.partner_id.name)
        self._create_aml_request_and_send_form()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("AML Form Sent"),
                'message': _("The KYC/AML form has been emailed to %s.") % self.partner_id.email,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_aml_bypass_wizard(self):
        """Open the reason-required popup for bypassing the AML/KYC check
        outright, instead of sending the client a form. Same restriction and
        one-request-per-order guard as action_send_aml_form."""
        self.ensure_one()
        self._check_aml_action_rights()
        if self.sudo().aml_request_ids:
            raise UserError(_("An AML request already exists for this order."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bypass AML/KYC Check'),
            'res_model': 'aml.bypass.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': self.id},
        }

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
        # Block confirming into a Sales Order until the AML/KYC gate is
        # cleared - either the process itself completed (form sent and
        # Approved/Bypassed) or the Quotation Approver recorded an override.
        # Hooked here rather than into action_confirm(): several other
        # installed modules also override action_confirm() and some (the
        # advance-payment wizard in project_extended_rk) return early without
        # calling super() on the first click, so an action_confirm() override
        # here could be skipped depending on module load order. Every path to
        # state='sale' still funnels through this write() - see core
        # sale.order.action_confirm()'s self.write(self._prepare_confirmation_values()).
        if vals.get('state') == 'sale':
            self._check_aml_gate(_("confirm this order"))

        trigger_override_bypass = bool(vals.get('aml_gate_override'))

        if self._AML_GATE_OVERRIDE_FIELDS.intersection(vals) and not self.env.su:
            self._check_aml_gate_override_rights()
            if vals.get('aml_gate_override'):
                has_reason = vals.get('aml_gate_override_reason') or any(
                    order.aml_gate_override_reason for order in self
                )
                if not has_reason:
                    raise UserError(_("Enter a reason before overriding the AML/KYC gate."))
                vals = dict(vals)
                vals['aml_gate_override_by'] = self.env.user.id
                vals['aml_gate_override_date'] = fields.Datetime.now()
            # The Quotation Approver may not have write access to a quotation
            # they do not own. A write limited to the override fields is
            # re-applied with elevated rights - the role check above is the
            # real gate; other fields are untouched.
            if set(vals) <= (self._AML_GATE_OVERRIDE_FIELDS
                             | {'aml_gate_override_by', 'aml_gate_override_date'}):
                res = self.sudo().write(vals)
                if trigger_override_bypass:
                    self._bypass_aml_requests_on_override()
                return res

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

        res = super().write(vals)
        if trigger_override_bypass:
            self._bypass_aml_requests_on_override()
        return res

    def _bypass_aml_requests_on_override(self):
        """Auto-bypass any AML request still sitting in an open pipeline stage
        once the linked order's AML/KYC gate is overridden. Without this the
        request stays wherever it was (e.g. still "New"), so its form keeps
        showing Accept/Bypass/Cancel etc. even though the gate is already
        Overridden and nothing about those buttons is still relevant."""
        for order in self:
            to_bypass = order.sudo().aml_request_ids.filtered(
                lambda r: r.state in self._AML_GATE_OVERRIDE_BYPASSABLE_STATES
            )
            if to_bypass:
                to_bypass.sudo().write({'state': 'bypassed'})
                for aml in to_bypass:
                    aml.sudo().message_post(
                        body=_("Request automatically bypassed because Sale Order %s's "
                               "AML/KYC gate was overridden.") % order.name
                    )

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
