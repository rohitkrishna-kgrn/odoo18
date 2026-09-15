from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # States on aml.request that count as the responsible person having
    # marked AML/KYC "Completed": either a full approval, or a manager
    # bypass (AML determined not required for this client).
    _AML_GATE_COMPLETED_STATES = ('approved', 'bypassed')

    # Pipeline stages that haven't reached a final outcome yet. Shared by
    # the cancel-cascade in write() and by aml_bypass_allowed below - both
    # need the same notion of "still open".
    _AML_OPEN_STATES = (
        'draft', 'new', 'accepted', 'in_progress',
        'hit_detected', 'additional_info', 'no_hit',
    )

    # Asked for only while a quotation is being created (the form view makes
    # it required on unsaved records). Existing quotations - including the
    # thousands that pre-date this module - stay editable without it.
    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', tracking=True)

    aml_request_ids = fields.One2many('aml.request', 'sale_order_id', string='AML Requests')
    aml_request_count = fields.Integer(compute='_compute_aml_request_count', string='AML Requests')

    # Logs the "form emailed to the client" milestone on the order's own
    # chatter via tracking.
    aml_form_status = fields.Selection([
        ('none', 'Not Sent'),
        ('sent', 'Sent to Customer'),
    ], string='AML Form Status', default='none', tracking=True, copy=False)

    # Stored (not just computed) so the "Pending AML" search filter can run
    # a plain domain against it; a non-stored field can't be searched.
    aml_gate_completed = fields.Boolean(
        string='AML/KYC Completed', compute='_compute_aml_gate_completed',
        store=True,
    )

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

    # Drives visibility of "AML Bypass" specifically. Unlike "Send AML Form"
    # (one-shot, hidden as soon as any request exists), Bypass stays
    # available for as long as the pipeline hasn't reached a final outcome -
    # including after the form has already been sent to the client, so the
    # AML team can change course mid-flight. Bypassing at that point expires
    # the KYC link already emailed to the client (see aml.bypass.wizard and
    # AmlPortalController, whose portal routes only serve a request that is
    # still in one of these open states).
    aml_bypass_allowed = fields.Boolean(
        string='Can Bypass AML/KYC Now',
        compute='_compute_aml_bypass_allowed',
    )

    @api.depends('aml_request_ids.state')
    def _compute_aml_bypass_allowed(self):
        for order in self:
            latest = order.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]
            order.aml_bypass_allowed = not latest or latest.state in self._AML_OPEN_STATES

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

    def _check_aml_gate(self, action_label=None):
        """Block a downstream action for this order's engagement until AML/KYC
        is Completed (Approved or Bypassed). ``action_label`` names the
        blocked action in the error message (defaults to the original
        project-creation caller's wording)."""
        action_label = action_label or _("create a project")
        for order in self:
            if order.aml_gate_completed:
                continue
            raise UserError(_(
                "Cannot %s for '%s': AML/KYC has not been marked Completed "
                "for this client yet. The AML team or the designated "
                "Quotation Approver can bypass the AML/KYC check from the "
                "sale order if an exception is needed."
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
        """Open the reason-required popup for bypassing the AML/KYC check -
        either outright (no request sent yet) or to close out a request
        that's already in progress, which also expires the KYC form link
        already emailed to the client. Refused once the pipeline has already
        reached a final outcome (see aml_bypass_allowed)."""
        self.ensure_one()
        self._check_aml_action_rights()
        if not self.aml_bypass_allowed:
            raise UserError(_(
                "This order's AML/KYC check has already reached a final "
                "outcome and can no longer be bypassed."
            ))
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
        # sudo(): the AML team clicking this button may not hold base write
        # access on sale.order (only Sales users normally do); this write
        # exists purely to log the tracked status change in the chatter.
        self.sudo().write({'aml_form_status': 'sent'})
        return aml

    def write(self, vals):
        # Block confirming into a Sales Order until the AML/KYC gate is
        # cleared - the form sent and Approved, or the check Bypassed.
        # Hooked here rather than into action_confirm(): several other
        # installed modules also override action_confirm() and some (the
        # advance-payment wizard in project_extended_rk) return early without
        # calling super() on the first click, so an action_confirm() override
        # here could be skipped depending on module load order. Every path to
        # state='sale' still funnels through this write() - see core
        # sale.order.action_confirm()'s self.write(self._prepare_confirmation_values()).
        if vals.get('state') == 'sale':
            self._check_aml_gate(_("confirm this order"))

        if vals.get('state') == 'cancel':
            for order in self:
                # Cancelling a quotation must not require AML rights.
                aml_to_cancel = order.sudo().aml_request_ids.filtered(
                    lambda r: r.state in self._AML_OPEN_STATES
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
        """Backs the header AML smart button, visible to every user once the
        form has been sent or bypassed. Only the AML team holds model access
        to aml.request (see ir.model.access.csv), so everyone else gets a
        plain status summary instead of the case file, rather than hitting
        an AccessError."""
        self.ensure_one()
        if not self.env.user.has_group('aml_automation_extended_rk.group_aml_user'):
            latest = self.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]
            state_labels = dict(self.env['aml.request']._fields['state'].selection)
            status = state_labels.get(latest.state) if latest else _('Not Sent')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AML / KYC Status'),
                    'message': _('Current AML/KYC status for this order: %s.') % status,
                    'type': 'info',
                    'sticky': False,
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('AML Requests'),
            'res_model': 'aml.request',
            'view_mode': 'list,form',
            'domain': [('sale_order_id', '=', self.id)],
            'context': {'default_sale_order_id': self.id},
        }
