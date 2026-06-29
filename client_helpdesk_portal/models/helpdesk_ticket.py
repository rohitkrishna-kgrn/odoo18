import html as _html
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PRIORITY_SELECTION = [
    ('0', 'Low'),
    ('1', 'Medium'),
    ('2', 'High'),
]

REQUEST_TYPE_SELECTION = [
    ('issue', 'Technical Issue'),
    ('complaint', 'Complaint'),
    ('other', 'General Request'),
]


class ClientHelpdeskTicket(models.Model):
    _name = 'client.helpdesk.ticket'
    _description = 'Client Helpdesk Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'ticket_number'

    # ── Identity ──────────────────────────────────────────────────────────────
    ticket_number = fields.Char(
        'Ticket Number', readonly=True, copy=False, index=True,
        default='New',
    )
    subject = fields.Char('Subject', required=True, tracking=True)

    # ── Client Details ────────────────────────────────────────────────────────
    client_name = fields.Char('Client Name', required=True, tracking=True)
    company_name = fields.Char('Company Name')
    email = fields.Char('Email Address', required=True, tracking=True)
    phone = fields.Char('Phone Number', required=True)
    reference_number = fields.Char('Reference / Customer ID')

    # ── Request Info ──────────────────────────────────────────────────────────
    request_type = fields.Selection(
        REQUEST_TYPE_SELECTION, string='Request Type',
        required=True, default='issue', tracking=True,
    )
    description = fields.Html('Description', required=True, sanitize=True)
    priority = fields.Selection(
        PRIORITY_SELECTION, string='Priority', default='0', tracking=True,
    )

    # ── Workflow ──────────────────────────────────────────────────────────────
    stage_id = fields.Many2one(
        'client.helpdesk.stage', string='Stage',
        group_expand='_read_group_stage_ids',
        default=lambda self: self._default_stage(),
        tracking=True, index=True,
    )
    kanban_state = fields.Selection([
        ('normal', 'In Progress'),
        ('done', 'Ready'),
        ('blocked', 'Blocked'),
    ], string='Kanban State', default='normal', tracking=True)

    user_id = fields.Many2one(
        'res.users', string='Assigned To',
        default=lambda self: self._default_assigned_to(),
        tracking=True, index=True,
    )
    internal_notes = fields.Html('Internal Notes', sanitize=True)

    # ── Attachments ───────────────────────────────────────────────────────────
    # M2M kept for backward compatibility; display uses attachment_ids instead.
    portal_attachment_ids = fields.Many2many(
        'ir.attachment',
        'helpdesk_portal_attachment_rel',
        'ticket_id', 'attachment_id',
        string='Client Attachments (M2M)',
    )
    # Authoritative list: every ir.attachment whose res_model/res_id point here.
    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id',
        domain=[('res_model', '=', 'client.helpdesk.ticket')],
        string='Attachments',
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    created_date = fields.Datetime(
        'Created Date', readonly=True, default=fields.Datetime.now,
    )
    last_updated = fields.Datetime(
        'Last Updated', readonly=True,
    )
    closed_date = fields.Datetime('Closed Date', readonly=True)

    # ── Company ───────────────────────────────────────────────────────────────
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, required=True,
    )

    active = fields.Boolean(default=True)

    # ── Computed helpers ──────────────────────────────────────────────────────
    is_closed = fields.Boolean(
        'Is Closed', related='stage_id.is_closed', store=True,
    )
    stage_name = fields.Char(related='stage_id.name', string='Stage Name', store=False)
    request_type_label = fields.Char(
        'Request Type Label', compute='_compute_request_type_label',
    )
    priority_label = fields.Char(
        'Priority Label', compute='_compute_priority_label',
    )
    portal_attachment_count = fields.Integer(
        'Client Attachments', compute='_compute_portal_attachment_count',
    )
    attachment_count = fields.Integer(
        'Attachments', compute='_compute_attachment_count',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Defaults & group expand
    # ─────────────────────────────────────────────────────────────────────────

    def _default_stage(self):
        return self.env['client.helpdesk.stage'].search([], order='sequence', limit=1)

    def _default_assigned_to(self):
        group = self.env.ref(
            'client_helpdesk_portal.group_helpdesk_manager',
            raise_if_not_found=False,
        )
        if group:
            return self.env['res.users'].search(
                [('groups_id', 'in', group.id), ('active', '=', True)], limit=1,
            )
        return False

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['client.helpdesk.stage'].search([])

    # ─────────────────────────────────────────────────────────────────────────
    # Compute
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('request_type')
    def _compute_request_type_label(self):
        mapping = dict(REQUEST_TYPE_SELECTION)
        for rec in self:
            rec.request_type_label = mapping.get(rec.request_type, '')

    @api.depends('priority')
    def _compute_priority_label(self):
        mapping = dict(PRIORITY_SELECTION)
        for rec in self:
            rec.priority_label = mapping.get(rec.priority, 'Low')

    @api.depends('portal_attachment_ids')
    def _compute_portal_attachment_count(self):
        for rec in self:
            rec.portal_attachment_count = len(rec.portal_attachment_ids)

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ticket_number', 'New') == 'New':
                vals['ticket_number'] = (
                    self.env['ir.sequence'].next_by_code('client.helpdesk.ticket')
                    or 'New'
                )
        records = super().create(vals_list)
        for rec in records:
            rec._send_client_acknowledgement()
            rec._notify_manager_new_ticket()
        return records

    def write(self, vals):
        vals['last_updated'] = fields.Datetime.now()
        # mark closed date when entering a closing stage
        if 'stage_id' in vals:
            new_stage = self.env['client.helpdesk.stage'].browse(vals['stage_id'])
            if new_stage.is_closed:
                vals['closed_date'] = fields.Datetime.now()
            else:
                vals['closed_date'] = False
        result = super().write(vals)
        if 'user_id' in vals:
            for rec in self:
                if rec.user_id:
                    rec._notify_agent_assignment()
                    rec._notify_manager_on_assignment()
        if 'stage_id' in vals:
            for rec in self:
                rec._notify_stage_change()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Email helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_company_info(self):
        company = self.company_id or self.env.company
        return {
            'name': company.name,
            'email': company.email or 'support@kgrnaudit.com',
            'phone': company.phone or '',
            'year': fields.Date.today().year,
        }

    def _html_email_wrapper(self, heading, content_rows, company):
        logo_url = "https://kompanyservices.com/wp-content/uploads/logo-kgrn.png"
        rows_html = ''.join(
            f'<tr><td style="padding:8px 15px;font-size:14px;border-bottom:1px solid #eee;">'
            f'<strong style="display:inline-block;min-width:160px;color:#004080;">{label}:</strong>'
            f'{value}</td></tr>'
            for label, value in content_rows
        )
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;">
<tr><td align="center">
  <table width="680" cellpadding="0" cellspacing="0"
         style="background:#fff;border:1px solid #dde2e8;border-radius:8px;margin:24px 0;">
    <tr>
      <td style="background:#003366;padding:24px;text-align:center;border-radius:8px 8px 0 0;">
        <img src="{logo_url}" alt="KGRN" width="90" height="90"
             style="display:block;margin:0 auto;" />
      </td>
    </tr>
    <tr><td style="padding:32px 30px;">
      <h2 style="color:#003366;margin:0 0 20px;font-size:20px;">{heading}</h2>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f0f6ff;border-left:5px solid #004080;border-radius:4px;">
        {rows_html}
      </table>
    </td></tr>
    <tr>
      <td style="background:#fafbfc;text-align:center;font-size:13px;color:#888;
                 padding:16px;border-radius:0 0 8px 8px;">
        &copy; {company['year']} {company['name']} &nbsp;|&nbsp;
        <a href="mailto:{company['email']}" style="color:#888;">{company['email']}</a>
      </td>
    </tr>
  </table>
</td></tr>
</table>
</body></html>"""

    def _send_client_acknowledgement(self):
        """Send acknowledgement email to the client who submitted the ticket."""
        if not self.email:
            return
        company = self._get_company_info()
        template = self.env.ref(
            'client_helpdesk_portal.mail_template_ticket_acknowledgement',
            raise_if_not_found=False,
        )
        if template:
            template.sudo().send_mail(self.id, force_send=True)
            return
        # fallback inline email
        rows = [
            ('Ticket Number', self.ticket_number),
            ('Subject', self.subject),
            ('Request Type', self.request_type_label),
            ('Priority', self.priority_label),
            ('Submitted On', fields.Datetime.now().strftime('%d %b %Y %H:%M')),
        ]
        body = self._html_email_wrapper(
            f'Thank you for contacting us, {self.client_name}!',
            rows, company,
        )
        self._send_mail(
            subject=f'[#{self.ticket_number}] Support Request Received – {self.subject}',
            body=body,
            email_to=self.email,
        )

    def _notify_manager_new_ticket(self):
        """Notify all Helpdesk Managers when a new ticket is created."""
        managers_group = self.env.ref(
            'client_helpdesk_portal.group_helpdesk_manager',
            raise_if_not_found=False,
        )
        if not managers_group:
            return
        manager_users = self.env['res.users'].search([
            ('groups_id', 'in', managers_group.id),
            ('active', '=', True),
        ])
        emails = ','.join(filter(None, manager_users.mapped('email')))
        if not emails:
            return
        template = self.env.ref(
            'client_helpdesk_portal.mail_template_new_ticket_manager',
            raise_if_not_found=False,
        )
        if template:
            try:
                template.sudo().send_mail(
                    self.id,
                    force_send=True,
                    email_values={'email_to': emails},
                )
            except Exception as exc:
                _logger.error('Manager notification error for ticket %s: %s', self.ticket_number, exc)
            return
        # Fallback: inline email
        company = self._get_company_info()
        rows = [
            ('Ticket #', self.ticket_number),
            ('Client', self.client_name),
            ('Company', self.company_name or '-'),
            ('Email', self.email),
            ('Phone', self.phone),
            ('Type', self.request_type_label),
            ('Priority', self.priority_label),
            ('Subject', self.subject),
        ]
        body = self._html_email_wrapper('New Helpdesk Ticket Submitted', rows, company)
        self._send_mail(
            subject=f'[New Ticket #{self.ticket_number}] {self.subject}',
            body=body,
            email_to=emails,
        )

    def _notify_agent_assignment(self):
        """Notify the assigned agent when a ticket is assigned to them."""
        if not self.user_id or not self.user_id.email:
            return
        template = self.env.ref(
            'client_helpdesk_portal.mail_template_agent_assignment',
            raise_if_not_found=False,
        )
        if template:
            try:
                template.sudo().send_mail(self.id, force_send=True)
            except Exception as exc:
                _logger.error('Agent assignment email error for ticket %s: %s', self.ticket_number, exc)
            return
        # Fallback: inline email
        company = self._get_company_info()
        rows = [
            ('Ticket #', self.ticket_number),
            ('Subject', self.subject),
            ('Client', self.client_name),
            ('Type', self.request_type_label),
            ('Priority', self.priority_label),
            ('Stage', self.stage_id.name or '-'),
        ]
        body = self._html_email_wrapper(
            f'You have been assigned Ticket #{self.ticket_number}',
            rows, company,
        )
        self._send_mail(
            subject=f'[Assigned #{self.ticket_number}] {self.subject}',
            body=body,
            email_to=self.user_id.email,
        )

    def _notify_stage_change(self):
        """
        Notification matrix for stage changes:
          Resolved / Closed  →  Client + Assigned User + Manager  (with remarks)
          All other stages   →  Client only  (via template)
        Reason/remarks are passed from the wizard via context keys:
          helpdesk_close_reason      — plain-text reason entered by the user
          helpdesk_close_action_type — 'resolve' | 'close'
        """
        if not self.stage_id:
            return
        if self.stage_id.name == 'New':
            return

        company = self._get_company_info()
        stage = self.stage_id.name

        if stage in ('Resolved', 'Closed'):
            reason      = self.env.context.get('helpdesk_close_reason', '')
            action_type = self.env.context.get('helpdesk_close_action_type', 'close')
            is_resolve  = (action_type == 'resolve') or (stage == 'Resolved')
            remarks_lbl = 'Resolution Remarks' if is_resolve else 'Closure Remarks'
            now_str     = fields.Datetime.now().strftime('%d %b %Y %H:%M')

            base_rows = [
                ('Ticket #',    self.ticket_number),
                ('Subject',     self.subject),
                ('Client',      self.client_name),
                ('Status',      stage),
                ('Updated On',  f'{now_str} UTC'),
            ]

            # 1 — Client
            if self.email:
                body = self._build_resolved_closed_body(
                    heading=f'Your Ticket has been {stage}',
                    intro=(
                        f'Your support ticket has been marked as <strong>{stage}</strong>. '
                        f'Please find the details below.'
                    ),
                    rows=base_rows,
                    remarks_lbl=remarks_lbl,
                    reason=reason,
                    company=company,
                )
                self._send_mail(
                    subject=f'[#{self.ticket_number}] Ticket {stage} – {self.subject}',
                    body=body,
                    email_to=self.email,
                )

            # 2 — Assigned User
            if self.user_id and self.user_id.email:
                body = self._build_resolved_closed_body(
                    heading=f'Ticket #{self.ticket_number} – {stage}',
                    intro=(
                        f'Ticket <strong>#{self.ticket_number}</strong> assigned to you '
                        f'has been marked as <strong>{stage}</strong>.'
                    ),
                    rows=base_rows,
                    remarks_lbl=remarks_lbl,
                    reason=reason,
                    company=company,
                )
                self._send_mail(
                    subject=f'[#{self.ticket_number}] Ticket {stage} – {self.subject}',
                    body=body,
                    email_to=self.user_id.email,
                )

            # 3 — Managers (exclude assigned user to avoid duplicate)
            managers_group = self.env.ref(
                'client_helpdesk_portal.group_helpdesk_manager',
                raise_if_not_found=False,
            )
            if managers_group:
                assigned_id = self.user_id.id if self.user_id else 0
                mgr_users   = self.env['res.users'].search([
                    ('groups_id', 'in', managers_group.id),
                    ('active',    '=',  True),
                    ('id',        '!=', assigned_id),
                ])
                mgr_emails = ','.join(filter(None, mgr_users.mapped('email')))
                if mgr_emails:
                    body = self._build_resolved_closed_body(
                        heading=f'Ticket #{self.ticket_number} – {stage}',
                        intro=(
                            f'Ticket <strong>#{self.ticket_number}</strong> '
                            f'has been marked as <strong>{stage}</strong>.'
                        ),
                        rows=base_rows,
                        remarks_lbl=remarks_lbl,
                        reason=reason,
                        company=company,
                    )
                    self._send_mail(
                        subject=f'[#{self.ticket_number}] Ticket {stage} – {self.subject}',
                        body=body,
                        email_to=mgr_emails,
                    )

        # Under Review / In Progress / Waiting for Client → no email sent

    def _notify_manager_on_assignment(self):
        """Notify managers when a ticket is assigned or re-assigned to a user."""
        if not self.user_id:
            return
        managers_group = self.env.ref(
            'client_helpdesk_portal.group_helpdesk_manager',
            raise_if_not_found=False,
        )
        if not managers_group:
            return
        # Exclude the assigned user from the manager list (they get their own email)
        mgr_users  = self.env['res.users'].search([
            ('groups_id', 'in', managers_group.id),
            ('active',    '=',  True),
            ('id',        '!=', self.user_id.id),
        ])
        mgr_emails = ','.join(filter(None, mgr_users.mapped('email')))
        if not mgr_emails:
            return
        template = self.env.ref(
            'client_helpdesk_portal.mail_template_manager_on_assignment',
            raise_if_not_found=False,
        )
        if template:
            try:
                template.sudo().send_mail(
                    self.id,
                    force_send=True,
                    email_values={'email_to': mgr_emails},
                )
            except Exception as exc:
                _logger.error('Manager assignment email error for ticket %s: %s', self.ticket_number, exc)
            return
        # Inline fallback
        company = self._get_company_info()
        rows = [
            ('Ticket #',    self.ticket_number),
            ('Subject',     self.subject),
            ('Client',      self.client_name),
            ('Assigned To', self.user_id.name),
            ('Type',        self.request_type_label),
            ('Priority',    self.priority_label),
            ('Stage',       self.stage_id.name or '—'),
        ]
        body = self._html_email_wrapper(
            f'Ticket #{self.ticket_number} Assigned to {self.user_id.name}',
            rows, company,
        )
        self._send_mail(
            subject=f'[Ticket #{self.ticket_number} Assigned] {self.subject}',
            body=body,
            email_to=mgr_emails,
        )

    def _build_resolved_closed_body(self, heading, intro, rows, remarks_lbl, reason, company):
        """Build a styled HTML email body for Resolved/Closed notifications.
        Includes a highlighted remarks block when a reason is provided."""
        logo_url = "https://kompanyservices.com/wp-content/uploads/logo-kgrn.png"
        rows_html = ''.join(
            f'<tr><td style="padding:10px 18px;font-size:14px;border-bottom:1px solid #dde8f7;">'
            f'<span style="display:inline-block;min-width:160px;font-weight:600;color:#004080;">{label}:</span>'
            f'{value}</td></tr>'
            for label, value in rows
        )
        if reason:
            reason_safe = _html.escape(reason).replace('\n', '<br/>')
            remarks_block = f"""
<div style="margin-top:20px;padding:16px 20px;background:#fff8e6;
            border-left:5px solid #f59e0b;border-radius:6px;">
  <p style="margin:0 0 8px;font-weight:700;font-size:14px;color:#92400e;">
    {_html.escape(remarks_lbl)}
  </p>
  <p style="margin:0;font-size:14px;color:#555555;line-height:1.7;">
    {reason_safe}
  </p>
</div>"""
        else:
            remarks_block = ''
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;">
<tr><td align="center" style="padding:24px 12px;">
  <table width="620" cellpadding="0" cellspacing="0"
         style="background:#ffffff;border:1px solid #dde2e8;border-radius:10px;overflow:hidden;">
    <tr>
      <td style="background:#003366;padding:28px 30px;text-align:center;">
        <img src="{logo_url}" alt="KGRN" width="90" height="90"
             style="display:block;margin:0 auto 12px;"/>
        <p style="margin:0;color:#ffffff;font-size:13px;letter-spacing:1px;
                  text-transform:uppercase;opacity:.8;">Support Center</p>
      </td>
    </tr>
    <tr>
      <td style="padding:32px 36px 28px;">
        <h2 style="margin:0 0 12px;color:#003366;font-size:20px;font-weight:700;">
          {_html.escape(heading)}
        </h2>
        <p style="margin:0 0 20px;color:#555555;font-size:14px;line-height:1.6;">
          {intro}
        </p>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:#f0f6ff;border-left:5px solid #0057b8;
                      border-radius:6px;margin-bottom:4px;">
          {rows_html}
        </table>
        {remarks_block}
      </td>
    </tr>
    <tr>
      <td style="background:#f5f7fa;padding:16px 36px;text-align:center;
                 border-top:1px solid #e8ecf0;">
        <p style="margin:0;font-size:12px;color:#999999;">
          &copy; {company['year']} {_html.escape(company['name'])} &nbsp;|&nbsp;
          <a href="mailto:{company['email']}"
             style="color:#0057b8;text-decoration:none;">{company['email']}</a>
        </p>
      </td>
    </tr>
  </table>
</td></tr>
</table>
</body></html>"""

    def _send_mail(self, subject, body, email_to):
        try:
            mail = self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': body,
                'email_to': email_to,
                'author_id': self.env.user.partner_id.id,
                'model': self._name,
                'res_id': self.id,
            })
            mail.sudo().send()
        except Exception as exc:
            _logger.error('Helpdesk email error for ticket %s: %s', self.ticket_number, exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Attachment actions
    # ─────────────────────────────────────────────────────────────────────────

    def action_view_portal_attachments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Client Attachments',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [
                ('res_model', '=', 'client.helpdesk.ticket'),
                ('res_id', '=', self.id),
            ],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Stage action buttons
    # ─────────────────────────────────────────────────────────────────────────

    def _move_to_stage(self, stage_name):
        for rec in self:
            if not rec.user_id:
                raise UserError(
                    'Please assign this ticket to a user before changing the stage.\n\n'
                    'Set the "Assigned To" field and save, then try again.'
                )
        stage = self.env['client.helpdesk.stage'].search(
            [('name', '=', stage_name)], limit=1,
        )
        if not stage:
            raise UserError(f'Stage "{stage_name}" not found. Please configure stages first.')
        self.write({'stage_id': stage.id})

    def action_set_under_review(self):
        self._move_to_stage('Under Review')

    def action_set_in_progress(self):
        self._move_to_stage('In Progress')

    def action_set_waiting(self):
        self._move_to_stage('Waiting for Client')

    def _open_action_wizard(self, action_type, title):
        if not self.user_id:
            raise UserError(
                'Please assign this ticket to a user before changing the stage.\n\n'
                'Set the "Assigned To" field and save, then try again.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'client.helpdesk.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_id': self.id,
                'default_action_type': action_type,
            },
        }

    def action_set_resolved(self):
        return self._open_action_wizard('resolve', 'Resolve Ticket')

    def action_set_closed(self):
        return self._open_action_wizard('close', 'Close Ticket')
