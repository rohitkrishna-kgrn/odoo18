from markupsafe import Markup, escape

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

    # "Send AML Form" is for the AML team while the quotation is To Approve;
    # the Quotation Approver only gets "AML Bypass" at that point.
    aml_is_aml_team = fields.Boolean(compute='_compute_aml_is_aml_team')

    @api.depends_context('uid')
    def _compute_aml_is_aml_team(self):
        is_team = self.env.user.has_group('aml_automation_extended_rk.group_aml_user')
        for order in self:
            order.aml_is_aml_team = is_team

    # ------------------------------------------------------------------
    # Submit for Approval -> AML Managers
    # ------------------------------------------------------------------
    def _notify_approval_submitted(self):
        """Replaces the Quotation Approver notification on submit: the AML
        Managers are told first. The approver is told once AML/KYC is
        Completed (see _notify_approver_aml_completed)."""
        self.ensure_one()
        if self.aml_gate_completed:
            self._notify_approver_aml_completed()
            return
        self._notify_aml_managers_submitted()

    def _aml_manager_users(self):
        group = self.env.ref('aml_automation_extended_rk.group_aml_manager')
        return self.env['res.users'].sudo().search([
            ('groups_id', 'in', group.ids), ('active', '=', True),
        ])

    def _aml_first_submitted_by(self):
        """Name of whoever moved the quotation to To Approve, read from the
        approval_state tracking. The approver email is sent by whoever
        completed AML, so env.user is the wrong person there."""
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

    def _notify_aml_managers_submitted(self):
        self.ensure_one()
        managers = self._aml_manager_users()
        sent_to = self._send_aml_first_mail(
            managers,
            subject=_("AML/KYC Check Required: Quotation %s") % self.name,
            title=_("Quotation Submitted - AML/KYC Check Required"),
            intro=_("Quotation <strong>%s</strong> has been submitted for approval. "
                    "Please complete the AML/KYC step first - send the AML/KYC form "
                    "to the client, or record a bypass with a reason. The Quotation "
                    "Approver can approve it once AML/KYC is Completed.") % escape(self.name),
            closing=_("Please open the quotation to send the AML/KYC form."),
            submitted_by=self.env.user.name,
        )
        if sent_to:
            note = _("Submitted for approval. AML/KYC check requested from the AML Manager(s): %s.",
                     ', '.join(managers.filtered('email').mapped('name')))
        else:
            note = _("Submitted for approval. No active AML Manager has an email "
                     "address, so no AML/KYC request email was sent.")
        self.sudo().message_post(body=note, author_id=self.env.user.partner_id.id)

    # ------------------------------------------------------------------
    # AML/KYC Completed -> Quotation Approver
    # ------------------------------------------------------------------
    def _aml_gate_snapshot(self):
        return {order.id: order.aml_gate_completed for order in self.sudo()}

    def _aml_notify_if_gate_cleared(self, before):
        if self.env.context.get('aml_first_skip_notify'):
            return
        for order in self.sudo():
            if before.get(order.id) or not order.aml_gate_completed:
                continue
            if order.approval_state == 'to_approve' and order.state in ('draft', 'sent'):
                order._notify_approver_aml_completed()

    def _notify_approver_aml_completed(self):
        """To-Do + email for the company's Quotation Approver once AML/KYC
        is Completed. The To-Do is closed by Approve itself (core
        sale_order_approval marks the approver's To-Dos done)."""
        self.ensure_one()
        order = self.sudo()
        approver = order.company_id.approver_user_id
        if not approver:
            return
        todo = self.env.ref('mail.mail_activity_data_todo')
        if not order.activity_ids.filtered(
                lambda a: a.user_id == approver and a.activity_type_id == todo):
            order.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=approver.id,
                summary=_("Approval Request"),
                note=_("AML/KYC is completed for quotation %s. It now needs your approval.") % order.name,
            )
        order._send_aml_first_mail(
            approver,
            subject=_("Approval Required: Quotation %s (AML/KYC Completed)") % order.name,
            title=_("AML/KYC Completed - Quotation Ready for Approval"),
            intro=_("AML/KYC for quotation <strong>%s</strong> is now Completed. "
                    "The quotation is waiting for your approval.") % escape(order.name),
            closing=_("Please open the quotation to approve it."),
            extra_rows=[(_('AML/KYC Completed By'), escape(self.env.user.name))],
        )
        order.message_post(
            body=Markup('<p>%s</p>') % _("AML/KYC Completed. Sent to the Quotation Approver (%s) for approval.",
                                         approver.name),
            author_id=self.env.user.partner_id.id,
        )

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------
    def action_approve_order(self):
        for order in self:
            if order.state == 'cancel':
                raise UserError(_("Quotation %s is cancelled and cannot be approved.", order.name))
        if not self.env.context.get('einvoicing_portal'):
            for order in self:
                if not order.aml_gate_completed:
                    raise UserError(_(
                        "Quotation %s cannot be approved yet: AML/KYC is not Completed. "
                        "The AML/KYC request must be Approved or Cancelled, or the "
                        "check bypassed, first.", order.name))
        return super().action_approve_order()

    def _notify_aml_team_order_approved(self):
        # AML/KYC is already done by the time an order can be approved, so
        # the old "approved - AML action needed" email would be noise.
        if self.aml_gate_completed:
            return
        return super()._notify_aml_team_order_approved()

    def action_send_aml_form(self):
        for order in self:
            if order.approval_state == 'to_approve' and not self.env.su \
                    and not self.env.user.has_group('aml_automation_extended_rk.group_aml_user'):
                raise UserError(_(
                    "Only the AML team can send the AML/KYC form while the quotation "
                    "is waiting for approval. The Quotation Approver can use AML Bypass."))
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
        # Cancelling an order cascades its open AML requests to 'cancelled',
        # which now ticks AML/KYC Completed - the approver must not be asked
        # to approve an order that is being cancelled.
        if vals.get('state') == 'cancel':
            return super(SaleOrder, self.with_context(aml_first_skip_notify=True)).write(vals)
        return super().write(vals)
