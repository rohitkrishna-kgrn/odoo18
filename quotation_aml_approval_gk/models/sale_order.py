from markupsafe import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ------------------------------------------------------------------
    # AML/KYC Completed
    # ------------------------------------------------------------------
    # Approved, Bypassed, or Cancelled by the AML team. A request that was
    # cancelled only because the quotation itself was cancelled
    # (cancelled_with_order) does NOT count - otherwise "Set to Quotation"
    # would bring the order back with AML already ticked.
    @api.depends('aml_request_ids.state', 'aml_request_ids.cancelled_with_order')
    def _compute_aml_gate_completed(self):
        for order in self:
            latest = order._aml_latest_request()
            order.aml_gate_completed = bool(latest) and (
                latest.state in ('approved', 'bypassed')
                or (latest.state == 'cancelled' and not latest.cancelled_with_order))

    def _aml_latest_request(self):
        self.ensure_one()
        return self.sudo().aml_request_ids.sorted('create_date', reverse=True)[:1]

    def _aml_restart_allowed(self):
        """The order was cancelled (taking its AML request with it) and then
        set back to quotation: the AML step starts over."""
        self.ensure_one()
        latest = self._aml_latest_request()
        return bool(latest) and latest.state == 'cancelled' and latest.cancelled_with_order

    @api.depends('aml_request_ids.state', 'aml_request_ids.cancelled_with_order')
    def _compute_aml_bypass_allowed(self):
        super()._compute_aml_bypass_allowed()
        for order in self:
            if order._aml_restart_allowed():
                order.aml_bypass_allowed = True

    # Send AML Form: no request yet, or the AML step was restarted.
    aml_can_send_form = fields.Boolean(compute='_compute_aml_can_send_form')

    @api.depends('aml_request_ids.state', 'aml_request_ids.cancelled_with_order')
    def _compute_aml_can_send_form(self):
        for order in self:
            order.aml_can_send_form = (
                not order.sudo().aml_request_ids or order._aml_restart_allowed())

    # Header status bar: approval_state, but "Cancelled" once the
    # quotation is cancelled.
    approval_status_display = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('cancel', 'Cancelled'),
    ], string='Status', compute='_compute_approval_status_display')

    @api.depends('state', 'approval_state')
    def _compute_approval_status_display(self):
        for order in self:
            order.approval_status_display = (
                'cancel' if order.state == 'cancel' else order.approval_state)

    # ------------------------------------------------------------------
    # Submit for Approval -> Quotation Approver only (sale_order_approval's
    # To-Do + email, in the branded layout below). The AML team is not
    # involved until the quotation is Approved.
    # ------------------------------------------------------------------
    def _approval_request_mail_body(self, approver):
        """Branded "Approval Required" email (same look as the AML emails)
        with an Open button that takes the approver straight to the quotation."""
        self.ensure_one()
        # Plain str + %, as in the other AML-first mails: passing Markup
        # arguments to _() escapes the template's own <br/>/<strong> tags.
        intro = _("Dear %s,<br/><br/>Quotation <strong>%s</strong> has been "
                  "submitted for your approval.") % (escape(approver.name), escape(self.name))
        body, _email_from = self._aml_first_email(
            title=_("Quotation Approval Required"),
            intro=intro,
            closing=_("Click the button below to open the quotation and approve it."),
            submitted_by=self.env.user.name,
        )
        # The shared AML shell signs off as the compliance team; this one
        # comes from the company, not the AML team.
        return body.replace('&nbsp;|&nbsp; UAE AML/CFT Compliance Team', '')

    def _aml_manager_users(self):
        group = self.env.ref('aml_automation_extended_rk.group_aml_manager')
        return self.env['res.users'].sudo().search([
            ('groups_id', 'in', group.ids), ('active', '=', True),
        ])

    def _aml_first_submitted_by(self):
        """Name of whoever moved the quotation to To Approve, read from the
        approval_state tracking (fallback when the caller doesn't pass it)."""
        self.ensure_one()
        tracking = self.env['mail.tracking.value'].sudo().search([
            ('field_id', '=', self.env['ir.model.fields']._get('sale.order', 'approval_state').id),
            ('new_value_char', '=', dict(self._fields['approval_state']._description_selection(self.env)).get('to_approve')),
            ('mail_message_id.model', '=', 'sale.order'),
            ('mail_message_id.res_id', '=', self.id),
        ], order='id desc', limit=1)
        return tracking.mail_message_id.author_id.name or ''

    def _aml_first_email(self, title, intro, closing, extra_rows=None, submitted_by=None):
        """Branded body in the same shell as every other AML email."""
        self.ensure_one()
        helper = self.env['aml.request'].sudo().new({'company_id': self.company_id.id})
        order_url = '%s/web#id=%s&model=sale.order&view_type=form' % (self.get_base_url(), self.id)
        body = helper._build_notification_body(
            intro,
            kv_rows=[
                (_('Quotation'), escape(self.name)),
                (_('Customer'), escape(self.partner_id.name or '')),
                # format() already carries the currency symbol (e.g. "1,050.00 AED").
                (_('Amount Total'), escape(self.currency_id.format(self.amount_total))),
                (_('Salesperson'), escape(self.user_id.name or '-')),
                (_('Submitted By'), escape(submitted_by or self._aml_first_submitted_by() or '-')),
            ] + list(extra_rows or []),
            closing=closing,
        ) + helper._email_cta_button(_('Open %s') % escape(self.name), order_url)
        return helper._email_shell(title=title, subtitle=escape(self.name), body_html=body), helper._get_mail_from()

    def _send_aml_first_mail(self, users, subject, title, intro, closing, extra_rows=None, submitted_by=None):
        emails = sorted({u.email for u in users if u.email})
        if not emails:
            return []
        body, email_from = self._aml_first_email(title, intro, closing, extra_rows, submitted_by)
        for email in emails:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body,
                'email_from': email_from,
                'email_to': email,
                'author_id': self.env.user.partner_id.id,
                'model': 'sale.order',
                'res_id': self.id,
            }).send()
        return emails

    # ------------------------------------------------------------------
    # Approve -> AML Managers
    # ------------------------------------------------------------------
    def _notify_aml_team_order_approved(self):
        """Replaces aml_automation's "approved - AML action needed" email to
        the whole AML team: only the AML Managers are told, once the
        quotation is Approved. Nothing is sent when AML/KYC is already
        Completed."""
        self.ensure_one()
        if self.aml_gate_completed:
            return
        managers = self._aml_manager_users()
        sent_to = self._send_aml_first_mail(
            managers,
            subject=_("Quotation %s Approved - AML/KYC Action Needed") % self.name,
            title=_("Quotation Approved - AML/KYC Action Needed"),
            intro=_("Quotation <strong>%s</strong> has been approved. Please complete "
                    "the AML/KYC step - send the AML/KYC form to the client, or record "
                    "a bypass with a reason.") % escape(self.name),
            closing=_("Click the button below to open the quotation."),
            extra_rows=[(_('Approved By'), escape(self.env.user.name))],
        )
        if sent_to:
            note = _("Approved. AML/KYC check requested from the AML Manager(s): %s.",
                     ', '.join(managers.filtered('email').mapped('name')))
        else:
            note = _("Approved. No active AML Manager has an email address, so no "
                     "AML/KYC request email was sent.")
        self.sudo().message_post(body=note, author_id=self.env.user.partner_id.id)

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def action_approve_order(self):
        for order in self:
            if order.state == 'cancel':
                raise UserError(_("Quotation %s is cancelled and cannot be approved.", order.name))
        return super().action_approve_order()

    def _check_aml_gate(self, action_label=None):
        """Once the quotation is Approved, AML/KYC no longer blocks Confirm
        (aml_automation_extended_rk's write(state='sale')) or the project
        that Confirm creates (project_extended_rk's project.create()). The
        AML step carries on alongside; only unapproved orders are checked."""
        pending = self.filtered(lambda o: o.approval_state != 'approved')
        if pending:
            return super(SaleOrder, pending)._check_aml_gate(action_label)

    def _aml_check_approved(self):
        for order in self:
            if order.approval_state != 'approved' and not self.env.su:
                raise UserError(_(
                    "The AML/KYC form can be sent, or the check bypassed, only once "
                    "quotation %s is Approved.", order.name))

    def action_open_aml_bypass_wizard(self):
        self._aml_check_approved()
        return super().action_open_aml_bypass_wizard()

    def action_send_aml_form(self):
        self._aml_check_approved()
        self.ensure_one()
        if self._aml_restart_allowed():
            # Core refuses once any request exists; the cancelled one stays
            # on record and a fresh request is sent.
            self._check_aml_action_rights()
            if not self.partner_id.email:
                raise UserError(_(
                    "%s does not have an email address on file. Add one before "
                    "sending the AML form.", self.partner_id.name))
            self._create_aml_request_and_send_form()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _("AML Form Sent"),
                    'message': _("The KYC/AML form has been emailed to %s.", self.partner_id.email),
                    'type': 'success',
                    'sticky': False,
                },
            }
        return super().action_send_aml_form()

    def write(self, vals):
        # Cancelling an order cascades its open AML requests to 'cancelled'.
        # The context marks those requests cancelled_with_order, so they do
        # not tick AML/KYC Completed (see aml.request.write).
        if vals.get('state') == 'cancel':
            return super(SaleOrder, self.with_context(aml_first_skip_notify=True)).write(vals)
        return super().write(vals)
