import html as _html
import logging
from datetime import timedelta
from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

GST_OFFSET = timedelta(hours=4)


def to_gst(dt):
    """Shift a naive UTC datetime (as stored/returned by Odoo) to Gulf
    Standard Time (UTC+4), for display purposes only — never for storage
    or comparisons."""
    return dt + GST_OFFSET if dt else dt

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

# Single brand palette for every helpdesk email — orange accents on a
# white background, used consistently by _build_email() so every
# notification and reminder looks like the same system.
BRAND_ORANGE = '#FF6A00'
BRAND_ORANGE_DARK = '#B84C00'
BRAND_ORANGE_LIGHT = '#FFF3E8'
BRAND_ORANGE_BORDER = '#FFD9B3'
BRAND_TEXT = '#333333'
BRAND_TEXT_MUTED = '#6b7280'
BRAND_PAGE_BG = '#f7f7f7'
DEFAULT_LOGO_URL = 'https://kompanyservices.com/wp-content/uploads/logo-kgrn.png'

STAGES_NOTIFYING_CLIENT_AND_STAFF = {'Resolved', 'Closed', 'Reopened'}


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
    company_name = fields.Char('Company Name', required=True)
    email = fields.Char('Email Address', required=True, tracking=True)
    phone = fields.Char('Phone Number', required=True)
    reference_number = fields.Char('Reference / Customer ID')
    requested_employee_id = fields.Many2one(
        'hr.employee', string='Requested Handler (Client Selected)',
        copy=False,
        help='Employee the client asked to handle this ticket, selected on '
             'the public submission form. Optional and informational — the '
             'authoritative owner is always "Assigned To".',
    )

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
    manager_user_ids = fields.Many2many(
        'res.users', string='Reporting Managers',
        compute='_compute_manager_user_ids', store=True,
        help='Every manager above the assigned user in the HR reporting '
             'chain. Drives Helpdesk Manager ticket visibility.',
    )
    manager_id = fields.Many2one(
        'res.users', string='Reporting Manager',
        compute='_compute_manager_user_ids', store=True,
        help='Direct manager of the assigned user, for grouping/filtering '
             '(e.g. Helpdesk Admin viewing tickets manager-wise).',
    )
    assignable_user_ids = fields.Many2many(
        'res.users', compute='_compute_assignable_user_ids',
        string='Assignable Users',
        help='Users the current login is allowed to reassign this ticket '
             'to — drives the "Assigned To" picker domain on the ticket '
             'form and kanban card. See _get_assignable_users().',
    )
    can_reassign = fields.Boolean(
        compute='_compute_can_reassign',
        help='Whether the current login may edit "Assigned To" at all '
             '(Helpdesk Admin/Manager) — drives the readonly state of that '
             'field on the ticket form. A single field node keeps this in '
             'one place instead of two group-gated field nodes, since '
             'Odoo\'s view compiler merges same-named field nodes\' '
             'domain/props by field name rather than per-node, which was '
             'silently dropping the domain for one of the two.',
    )
    internal_notes = fields.Html('Internal Notes', sanitize=True)
    resume_reason = fields.Text(
        'Reason to In Progress (Legacy)', readonly=True, copy=False,
        help='Deprecated — superseded by resume_reason_line_ids. Kept only '
             'so historical data survives for the reason-line migration; no '
             'longer written to or shown in any view.',
    )
    resume_reason_line_ids = fields.One2many(
        'client.helpdesk.reason.line', 'ticket_id',
        domain=[('action_type', '=', 'resume')], string='Resume History',
    )
    closed_reason_line_ids = fields.One2many(
        'client.helpdesk.reason.line', 'ticket_id',
        domain=[('action_type', 'in', ('resolve', 'close', 'reopen'))],
        string='Resolution / Closure History',
    )

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
    reopened_date = fields.Datetime(
        'Reopened Date', readonly=True, copy=False,
        help='Set each time the ticket (re-)enters the Reopened stage — '
             'the reference point for Reopened-stage reminder emails, '
             'separate from the original created_date.',
    )
    last_reminder_sent_at = fields.Datetime(
        readonly=True, copy=False,
        help='When the last New/Reopened stage reminder email went out. '
             'Cleared on every stage change so re-entering a reminder '
             "stage later starts a fresh 2-day cycle. Prevents the cron "
             'from sending duplicate reminders within the same window.',
    )

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
    # mail.thread overrides
    # ─────────────────────────────────────────────────────────────────────────

    def _message_auto_subscribe_followers(self, updated_values, default_subtype_ids):
        """Suppress mail.thread's generic "You have been assigned to..."
        notification (mail.message_user_assigned) that Odoo core fires
        automatically for any model with a tracked user_id field — this
        model already sends a fully branded assignment email for every
        case via _notify_assignment(); without this override, the
        assigned user would get both, and the core one doesn't match the
        orange/white template."""
        return []

    # ─────────────────────────────────────────────────────────────────────────
    # Defaults & group expand
    # ─────────────────────────────────────────────────────────────────────────

    def _default_stage(self):
        return self.env['client.helpdesk.stage'].search([], order='sequence', limit=1)

    def _default_assigned_to(self):
        return self._get_helpdesk_admin_user()

    def _get_helpdesk_admin_user(self):
        """Return the currently configured Helpdesk Admin user (falls back
        to the default administrator account if unset/invalid/inactive)."""
        icp = self.env['ir.config_parameter'].sudo()
        admin_id = icp.get_param('client_helpdesk_portal.helpdesk_admin_user_id')
        user = self.env['res.users']
        if admin_id:
            candidate = self.env['res.users'].browse(int(admin_id)).exists()
            if candidate.active:
                user = candidate
        if not user:
            fallback = self.env.ref('base.user_admin', raise_if_not_found=False)
            if fallback and fallback.exists() and fallback.active:
                user = fallback
        return user

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return self.env['client.helpdesk.stage'].search([])

    @api.onchange('requested_employee_id')
    def _onchange_requested_employee_id(self):
        """Keep Assigned To in sync with the Client Requested Handler while
        the ticket is still being drafted (before the first save)."""
        if self.requested_employee_id and self.requested_employee_id.user_id:
            self.user_id = self.requested_employee_id.user_id

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

    @api.depends('user_id')
    def _compute_manager_user_ids(self):
        for rec in self:
            managers = self.env['res.users']
            direct_manager = self.env['res.users']
            current = rec.user_id.employee_id.parent_id if rec.user_id else self.env['hr.employee']
            visited, depth = set(), 0
            while current and current.id not in visited and depth < 20:
                visited.add(current.id)
                if current.user_id:
                    managers |= current.user_id
                    if not direct_manager:
                        direct_manager = current.user_id
                current, depth = current.parent_id, depth + 1
            rec.manager_user_ids = managers
            rec.manager_id = direct_manager

    def _compute_assignable_user_ids(self):
        assignable = self._get_assignable_users()
        for rec in self:
            rec.assignable_user_ids = assignable

    def _compute_can_reassign(self):
        can_reassign = self.env.user.has_group('client_helpdesk_portal.group_helpdesk_manager')
        for rec in self:
            rec.can_reassign = can_reassign

    # ─────────────────────────────────────────────────────────────────────────
    # Reassignment access
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def _get_assignable_users(self):
        """Users the current login is allowed to (re)assign a ticket to.

        Helpdesk Admin: any user with "Select Access" enabled in Helpdesk
        Portal Users (Configuration) — the sole criterion, no active-login
        requirement. Helpdesk Manager: same, but limited to their own team
        (employee's direct manager = the current user, same scoping as
        rule_portal_user_manager_team). Anyone else: none — they cannot
        reassign at all, enforced in write()/create()."""
        base_domain = [
            ('select_access', '=', True),
            ('user_id', '!=', False),
        ]
        if self.env.user.has_group('client_helpdesk_portal.group_helpdesk_admin'):
            domain = base_domain
        elif self.env.user.has_group('client_helpdesk_portal.group_helpdesk_manager'):
            domain = base_domain + [('employee_id.parent_id.user_id', '=', self.env.user.id)]
        else:
            return self.env['res.users']
        return self.env['client.helpdesk.portal.user'].sudo().search(domain).user_id

    def _check_reassign_access(self, new_user_id):
        is_admin = self.env.user.has_group('client_helpdesk_portal.group_helpdesk_admin')
        is_manager = self.env.user.has_group('client_helpdesk_portal.group_helpdesk_manager')
        if not is_admin and not is_manager:
            raise AccessError('Only the Helpdesk Admin or Helpdesk Manager can reassign tickets.')
        if new_user_id and new_user_id not in self._get_assignable_users().ids:
            scope = 'in Helpdesk Portal Users configuration' if is_admin else 'on your team with Select Access enabled'
            raise AccessError(f'You can only reassign tickets to users {scope}.')

    # ─────────────────────────────────────────────────────────────────────────
    # ORM overrides
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        admin_user = self._get_helpdesk_admin_user()
        for vals in vals_list:
            # An explicit Assigned To on manual (non-portal) creation is
            # held to the same rules as reassignment via write(); the
            # portal controller creates through sudo() and is exempt, same
            # as write(). The auto-filled defaults below (client-requested
            # employee, or the Helpdesk Admin fallback) are always valid
            # and don't need this check.
            if vals.get('user_id') and not self.env.su:
                self._check_reassign_access(vals['user_id'])
            if vals.get('ticket_number', 'New') == 'New':
                vals['ticket_number'] = (
                    self.env['ir.sequence'].next_by_code('client.helpdesk.ticket')
                    or 'New'
                )
            employee = self.env['hr.employee']
            emp_id = vals.get('requested_employee_id')
            if emp_id:
                employee = self.env['hr.employee'].sudo().browse(emp_id).exists()
            if not vals.get('user_id'):
                if employee and employee.user_id:
                    vals['user_id'] = employee.user_id.id
                elif admin_user:
                    vals['user_id'] = admin_user.id
        records = super().create(vals_list)
        for rec in records:
            # Ticket created -> Client only. Assignment (to whoever
            # user_id ends up being, including the Helpdesk Admin
            # fallback above) is a separate event, notified below.
            rec._notify_client_new_ticket()
            rec._notify_assignment()
        return records

    def write(self, vals):
        if 'user_id' in vals and not self.env.su:
            self._check_reassign_access(vals['user_id'])

        vals['last_updated'] = fields.Datetime.now()
        # mark closed date when entering a closing stage
        if 'stage_id' in vals:
            new_stage = self.env['client.helpdesk.stage'].browse(vals['stage_id'])
            if new_stage.is_closed:
                vals['closed_date'] = fields.Datetime.now()
            else:
                vals['closed_date'] = False
            if new_stage.name == 'Reopened':
                vals['reopened_date'] = fields.Datetime.now()
            # Any stage change (re-)starts the reminder clock for
            # whichever of New/Reopened the ticket is now in, if any.
            vals['last_reminder_sent_at'] = False
        result = super().write(vals)
        if 'user_id' in vals:
            for rec in self:
                rec._notify_assignment()
        if 'stage_id' in vals:
            for rec in self:
                rec._notify_stage_change()
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Email helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fmt_gst(self, dt):
        """Format a UTC datetime as Gulf Standard Time, for display in
        emails."""
        dt_gst = to_gst(dt)
        return dt_gst.strftime('%d %b %Y at %H:%M') if dt_gst else ''

    def _get_company_info(self):
        company = self.company_id or self.env.company
        logo_url = (
            f'{self.get_base_url()}/web/image/res.company/{company.id}/logo'
            if company.logo else DEFAULT_LOGO_URL
        )
        return {
            'name': company.name,
            'email': company.email or 'support@kgrnaudit.com',
            'phone': company.phone or '',
            'year': fields.Date.today().year,
            'logo_url': logo_url,
        }

    def _build_email(self, header_label, heading, intro, rows, company,
                      cta_url=None, cta_label='Open Ticket',
                      remarks_label=None, remarks_text=None, remarks_color='orange'):
        """Single source of truth for every helpdesk email's HTML/CSS —
        orange header banner (title + logo) on an otherwise white body,
        fluid width with a mobile breakpoint. Every notification and
        reminder email builds through this one method so the whole
        system looks consistent.

        remarks_color: 'orange' (default) or 'green' — Resolved uses
        green to read as a positive outcome; Closed/Reopened keep the
        brand orange."""
        rows_html = ''.join(
            f'<tr><td style="padding:10px 18px;font-size:14px;'
            f'{"" if i == len(rows) - 1 else "border-bottom:1px solid " + BRAND_ORANGE_BORDER + ";"}">'
            f'<span style="display:inline-block;min-width:150px;font-weight:600;color:{BRAND_ORANGE_DARK};">'
            f'{_html.escape(label)} :</span> {value}</td></tr>'
            for i, (label, value) in enumerate(rows)
        )
        remarks_block = ''
        if remarks_text:
            if remarks_color == 'green':
                r_bg, r_border, r_label_color = '#eafbf0', '#22c55e', '#15803d'
            else:
                r_bg, r_border, r_label_color = BRAND_ORANGE_LIGHT, BRAND_ORANGE, BRAND_ORANGE_DARK
            reason_safe = _html.escape(remarks_text).replace('\n', '<br/>')
            remarks_block = f"""
<div style="margin-top:20px;padding:16px 20px;background:{r_bg};
            border-left:4px solid {r_border};border-radius:6px;">
  <p style="margin:0 0 8px;font-weight:700;font-size:14px;color:{r_label_color};">
    {_html.escape(remarks_label or 'Remarks')}
  </p>
  <p style="margin:0;font-size:14px;color:#555555;line-height:1.7;">{reason_safe}</p>
</div>"""
        cta_button = ''
        if cta_url:
            cta_button = f"""
<div style="margin-top:24px;text-align:center;">
  <a href="{cta_url}" style="display:inline-block;background:{BRAND_ORANGE};color:#ffffff;
            text-decoration:none;font-weight:700;font-size:14px;padding:12px 32px;
            border-radius:6px;">{_html.escape(cta_label)}</a>
</div>"""
        phone_part = f'&nbsp;|&nbsp;{_html.escape(company["phone"])}' if company.get('phone') else ''
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<style>
@media only screen and (max-width: 700px) {{
  .hd-container {{ width:100% !important; }}
  .hd-pad {{ padding:20px !important; }}
  .hd-logo {{ width:52px !important; height:52px !important; }}
}}
</style>
</head>
<body style="margin:0;padding:0;background:{BRAND_PAGE_BG};font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BRAND_PAGE_BG};">
<tr><td align="center" style="padding:24px 12px;">
  <table role="presentation" class="hd-container" width="760" cellpadding="0" cellspacing="0"
         style="width:760px;max-width:760px;background:#ffffff;border:1px solid {BRAND_ORANGE_BORDER};
                border-radius:10px;overflow:hidden;">
    <tr>
      <td style="background:{BRAND_ORANGE};padding:26px 40px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>
            <td style="vertical-align:middle;">
              <p style="margin:0;color:#ffffff;font-size:20px;font-weight:700;
                        letter-spacing:.5px;text-transform:uppercase;">{_html.escape(header_label)}</p>
            </td>
            <td style="vertical-align:middle;text-align:right;">
              <table role="presentation" cellpadding="0" cellspacing="0" style="display:inline-table;
                     background:#ffffff;border-radius:8px;">
                <tr><td style="padding:6px 10px;">
                  <img class="hd-logo" src="{company['logo_url']}" alt="{_html.escape(company['name'])}"
                       width="72" height="72"
                       style="display:block;max-width:72px;max-height:72px;border:0;"/>
                </td></tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr>
      <td class="hd-pad" style="padding:36px 40px;">
        <h2 style="margin:0 0 12px;color:{BRAND_ORANGE_DARK};font-size:20px;font-weight:700;">{heading}</h2>
        <p style="margin:0 0 20px;color:{BRAND_TEXT};font-size:14px;line-height:1.6;">{intro}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background:{BRAND_ORANGE_LIGHT};border-left:4px solid {BRAND_ORANGE};border-radius:6px;">
          {rows_html}
        </table>
        {remarks_block}
        {cta_button}
      </td>
    </tr>
    <tr>
      <td style="background:#ffffff;padding:18px 40px;text-align:center;border-top:2px solid {BRAND_ORANGE};">
        <p style="margin:0;font-size:12px;color:{BRAND_TEXT_MUTED};">
          &copy; {company['year']} {_html.escape(company['name'])} &nbsp;|&nbsp;
          <a href="mailto:{company['email']}"
             style="color:{BRAND_ORANGE_DARK};text-decoration:none;">{company['email']}</a>{phone_part}
        </p>
      </td>
    </tr>
  </table>
</td></tr>
</table>
</body>
</html>"""

    def _notify_client_new_ticket(self):
        """Ticket created -> notify the Client only. Assignment (whoever
        ends up as user_id, including the Helpdesk Admin fallback) is a
        distinct event handled by _notify_assignment()."""
        if not self.email:
            return
        company = self._get_company_info()
        rows = [
            ('Ticket Number', self.ticket_number),
            ('Subject', self.subject),
            ('Request Type', self.request_type_label),
            ('Priority', self.priority_label),
            ('Submitted On', f'{self._fmt_gst(self.created_date)} GST'),
        ]
        body = self._build_email(
            header_label='Support Center',
            heading=f'Thank you for contacting us, {_html.escape(self.client_name or "")}!',
            intro='We have received your support request and our team will review it shortly. '
                  'Your ticket reference is shown below — please keep it for any follow-up.',
            rows=rows, company=company,
            cta_url=self._get_track_ticket_url(), cta_label='Track Ticket',
        )
        self._send_mail(
            subject=f'[{self.ticket_number}] Support Request Received – {self.subject}',
            body=body,
            email_to=self.email,
        )

    def _get_notifiable_manager(self):
        """The one manager who should hear about this ticket: the assigned
        user's direct manager — excluding the Helpdesk Admin (who is never
        notified via the "manager" channel) and the assigned user
        themselves."""
        manager = self.manager_id
        if not manager or manager == self.user_id:
            return self.env['res.users']
        admin_group = self.env.ref('client_helpdesk_portal.group_helpdesk_admin', raise_if_not_found=False)
        if admin_group and admin_group in manager.groups_id:
            return self.env['res.users']
        return manager

    def _notify_assignment(self):
        """Ticket assigned (creation or reassignment alike) -> notify the
        Assigned User, and separately their direct Manager if any. Covers
        every case in one place: a client-requested handler, a manual
        (re)assignment by Admin/Manager, and the Helpdesk Admin fallback
        when no user was selected at creation — whoever user_id is, they
        get this email."""
        if not self.user_id or not self.user_id.email:
            return
        company = self._get_company_info()
        rows = [
            ('Ticket Number', self.ticket_number),
            ('Subject', self.subject),
            ('Client', self.client_name),
            ('Request Type', self.request_type_label),
            ('Priority', self.priority_label),
            ('Current Stage', self.stage_id.name or '—'),
        ]
        body = self._build_email(
            header_label='Ticket Assignment',
            heading=f'Hello {_html.escape(self.user_id.name)},',
            intro=f'Ticket <strong>{self.ticket_number}</strong> has been assigned to you. '
                  'Please review the details below and take the appropriate action.',
            rows=rows, company=company,
            cta_url=self._get_backend_ticket_url(), cta_label='Open Ticket',
        )
        self._send_mail(
            subject=f'[Assigned {self.ticket_number}] {self.subject}',
            body=body,
            email_to=self.user_id.email,
        )

        manager = self._get_notifiable_manager()
        if manager and manager.email:
            manager_rows = rows + [
                ('Assigned To', f'{self.user_id.name} ({self.user_id.email or "—"})'),
            ]
            manager_body = self._build_email(
                header_label='Ticket Assignment',
                heading=f'Ticket Assigned to {_html.escape(self.user_id.name)}',
                intro=f'Ticket <strong>{self.ticket_number}</strong> has been assigned to '
                      f'<strong>{_html.escape(self.user_id.name)}</strong>, a member of your team. '
                      'Please find the ticket details below.',
                rows=manager_rows, company=company,
                cta_url=self._get_backend_ticket_url(), cta_label='Open Ticket',
            )
            self._send_mail(
                subject=f'[Ticket {self.ticket_number} Assigned] {self.subject}',
                body=manager_body,
                email_to=manager.email,
            )

    def _notify_stage_change(self):
        """Resolved / Closed / Reopened -> Client + Assigned User +
        Assigned User's direct Manager (never the Helpdesk Admin, never a
        manager unrelated to this ticket). Every other stage change sends
        nothing. Remarks come from context — set by the close wizard for
        resolve/close, and by action_reopen_by_client for reopen:
          helpdesk_close_reason      — plain-text reason entered by the user
          helpdesk_close_action_type — 'resolve' | 'close' | 'reopen'
        """
        if not self.stage_id or self.stage_id.name not in STAGES_NOTIFYING_CLIENT_AND_STAFF:
            return

        stage = self.stage_id.name
        reason = self.env.context.get('helpdesk_close_reason', '')
        action_type = self.env.context.get('helpdesk_close_action_type') or (
            'reopen' if stage == 'Reopened' else 'close'
        )
        remarks_label = {
            'resolve': 'Resolution Remarks',
            'close': 'Closed Remarks',
            'reopen': 'Reopen Reason',
        }.get(action_type, 'Remarks')
        remarks_color = 'green' if action_type == 'resolve' else 'orange'

        company = self._get_company_info()
        now_str = f'{self._fmt_gst(fields.Datetime.now())} GST'
        base_rows = [
            ('Ticket Number', self.ticket_number),
            ('Subject', self.subject),
            ('Client', self.client_name),
            ('Status', stage),
            ('Updated On', now_str),
        ]

        # 1 — Client
        if self.email:
            body = self._build_email(
                header_label='Ticket Status Update',
                heading=f'Your Ticket has been {stage}',
                intro=f'Your support ticket has been marked as <strong>{stage}</strong>. '
                      'Please find the details below.',
                rows=base_rows, company=company,
                cta_url=self._get_track_ticket_url(), cta_label='Track Ticket',
                remarks_label=remarks_label, remarks_text=reason, remarks_color=remarks_color,
            )
            self._send_mail(
                subject=f'[{self.ticket_number}] Ticket {stage} – {self.subject}',
                body=body,
                email_to=self.email,
            )

        if not self.user_id:
            return
        staff_rows = base_rows + [('Assigned To', self.user_id.name)]

        # 2 — Assigned User
        if self.user_id.email:
            body = self._build_email(
                header_label='Ticket Status Update',
                heading=f'Ticket {self.ticket_number} – {stage}',
                intro=f'Ticket <strong>{self.ticket_number}</strong> assigned to you '
                      f'has been marked as <strong>{stage}</strong>.',
                rows=staff_rows, company=company,
                cta_url=self._get_backend_ticket_url(), cta_label='Open Ticket',
                remarks_label=remarks_label, remarks_text=reason, remarks_color=remarks_color,
            )
            self._send_mail(
                subject=f'[{self.ticket_number}] Ticket {stage} – {self.subject}',
                body=body,
                email_to=self.user_id.email,
            )

        # 3 — Assigned User's direct Manager only (never the Admin, never
        # an unrelated manager).
        manager = self._get_notifiable_manager()
        if manager and manager.email:
            body = self._build_email(
                header_label='Ticket Status Update',
                heading=f'Ticket {self.ticket_number} – {stage}',
                intro=f'Ticket <strong>{self.ticket_number}</strong>, assigned to a member of '
                      f'your team, has been marked as <strong>{stage}</strong>.',
                rows=staff_rows, company=company,
                cta_url=self._get_backend_ticket_url(), cta_label='Open Ticket',
                remarks_label=remarks_label, remarks_text=reason, remarks_color=remarks_color,
            )
            self._send_mail(
                subject=f'[{self.ticket_number}] Ticket {stage} – {self.subject}',
                body=body,
                email_to=manager.email,
            )

    # ─────────────────────────────────────────────────────────────────────────
    # New/Reopened stage reminders (Scheduled Action)
    # ─────────────────────────────────────────────────────────────────────────

    _REMINDER_STAGE_REF_FIELDS = (('New', 'created_date'), ('Reopened', 'reopened_date'))

    @api.model
    def _cron_send_stage_reminders(self):
        """Every 2 days, remind the Assigned User (Admin/Manager/User —
        whoever it is) while a ticket sits in New (clock starts at
        created_date) or Reopened (clock starts at reopened_date), until
        it moves to another stage. last_reminder_sent_at gates re-sends so
        this stays duplicate-free even if the cron runs more than once
        inside the same 2-day window.

        "Run Manually" (Settings > Technical > Scheduled Actions) skips
        that duplicate-prevention gate — someone testing the feature
        expects a click to actually send, not to silently no-op because
        an earlier test already reminded the same ticket. The real "must
        be pending >= 2 days" eligibility rule still applies either way,
        so this never sends a same-day-old ticket a reminder that
        wouldn't make sense yet. Odoo's real scheduled execution always
        carries a 'cron_id' context key (see ir.cron._run_job); a manual
        trigger (ir.cron.method_direct_trigger) never sets it — that's
        the reliable signal used here, not a guess."""
        is_manual_run = not self.env.context.get('cron_id')
        now = fields.Datetime.now()
        checked = sent = 0
        skipped_too_fresh = skipped_gated = 0
        for stage_name, ref_field in self._REMINDER_STAGE_REF_FIELDS:
            stage = self.env['client.helpdesk.stage'].search([('name', '=', stage_name)], limit=1)
            if not stage:
                continue
            for ticket in self.search([('stage_id', '=', stage.id)]):
                ref_date = ticket[ref_field]
                if not ref_date:
                    continue
                checked += 1
                pending_days = (now - ref_date).days
                if pending_days < 2:
                    skipped_too_fresh += 1
                    continue
                if not is_manual_run and ticket.last_reminder_sent_at and (now - ticket.last_reminder_sent_at).days < 2:
                    skipped_gated += 1
                    continue
                ticket._send_stage_reminder(stage_name, pending_days)
                sent += 1
                # Direct SQL, not ticket.write(): a reminder isn't a real
                # content change and shouldn't bump last_updated or
                # re-trigger any write()-side notification logic.
                self.env.cr.execute(
                    'UPDATE client_helpdesk_ticket SET last_reminder_sent_at = %s WHERE id = %s',
                    (now, ticket.id),
                )
                ticket.invalidate_recordset(['last_reminder_sent_at'])
        # Run Manually (Settings > Technical > Scheduled Actions) gives no
        # UI feedback either way, and "correctly found nothing to send" is
        # indistinguishable from "broken" without this — so always log a
        # summary, not just on errors.
        _logger.info(
            'Helpdesk stage reminders (%s run): %s ticket(s) checked, %s sent, '
            '%s skipped (< 2 days pending), %s skipped (reminded within last 2 days).',
            'manual' if is_manual_run else 'scheduled',
            checked, sent, skipped_too_fresh, skipped_gated,
        )

    def _send_stage_reminder(self, stage_name, pending_days):
        """Assigned User only — no Helpdesk Admin copy. If the ticket has
        no Assigned User, there's no one to remind, so nothing is sent."""
        if not self.user_id or not self.user_id.email:
            return
        recipient_emails = {self.user_id.email}
        company = self._get_company_info()
        rows = [
            ('Ticket Number', self.ticket_number),
            ('Subject', self.subject),
            ('Client Name', self.client_name),
            ('Current Stage', stage_name),
            ('Pending Days', str(pending_days)),
        ]
        body = self._build_email(
            header_label='Ticket Reminder',
            heading=f'Reminder: Ticket {self.ticket_number} needs attention',
            intro=f'This ticket has been in the <strong>{stage_name}</strong> stage for '
                  f'<strong>{pending_days} day(s)</strong>. Please review and take action.',
            rows=rows, company=company,
            cta_url=self._get_backend_ticket_url(), cta_label='Open Ticket',
        )
        self._send_mail(
            subject=f'[Reminder {self.ticket_number}] {stage_name} for {pending_days} day(s)',
            body=body,
            email_to=','.join(sorted(recipient_emails)),
        )

    def _send_mail(self, subject, body, email_to):
        mail = self.env['mail.mail']
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
        self._log_email_notification(subject, email_to, mail)

    def _infer_recipient_label(self, address):
        """Best-effort label for the Notifications log — matches the "To"
        address against this ticket's known people at send time. Not
        stored on the recipient itself since a user's email can change
        later; this is a point-in-time label, same spirit as
        ticket_number/client_name being copied onto the log row."""
        address = (address or '').strip().lower()
        if not address:
            return 'Unknown'
        if self.email and address == self.email.strip().lower():
            return 'Client'
        if self.user_id and self.user_id.email and address == self.user_id.email.strip().lower():
            return 'Assigned User'
        admin = self._get_helpdesk_admin_user()
        if admin and admin.email and address == admin.email.strip().lower():
            return 'Helpdesk Admin'
        manager = self._get_notifiable_manager()
        if manager and manager.email and address == manager.email.strip().lower():
            return 'Manager'
        return 'Other'

    def _log_email_notification(self, subject, email_to, mail):
        """Record one Notifications-log row per recipient address — some
        sends (e.g. reminders) comma-join multiple addresses into one
        mail.mail, and each recipient deserves their own labeled row
        rather than one row listing everyone."""
        company_email = (self.company_id or self.env.company).email or ''
        addresses = [a.strip() for a in (email_to or '').split(',') if a.strip()]
        if not addresses:
            return
        NotificationLog = self.env['client.helpdesk.notification.log'].sudo()
        NotificationLog.create([{
            'ticket_id': self.id,
            'event_type': 'email',
            'date_time': fields.Datetime.now(),
            'email_from': company_email,
            'email_to': address,
            'recipient_label': self._infer_recipient_label(address),
            'subject': subject,
            'mail_id': mail.id if mail else False,
        } for address in addresses])

    def _get_backend_ticket_url(self):
        self.ensure_one()
        return f'{self.get_base_url()}/web#id={self.id}&view_type=form&model=client.helpdesk.ticket'

    def _get_track_ticket_url(self):
        self.ensure_one()
        return f'{self.get_base_url()}/helpdesk/track/{self.ticket_number}'

    def _track_progress_steps(self):
        """Ordered list of {name, state} for the public Track Ticket page's
        progress widget, mapped onto the real stages (no invented "Assigned"
        step) — state is 'done' / 'current' / 'upcoming' relative to this
        ticket's current stage sequence."""
        self.ensure_one()
        stages = self.env['client.helpdesk.stage'].search([], order='sequence')
        current_seq = self.stage_id.sequence
        return [{
            'name': s.name,
            'state': 'done' if s.sequence < current_seq
                     else 'current' if s.id == self.stage_id.id
                     else 'upcoming',
        } for s in stages]

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
        self.ensure_one()
        if self.stage_id.name == 'Waiting for Client':
            # Resuming after the client responded — ask why before moving
            # the ticket back, and keep that reason on record.
            return self._open_action_wizard('resume', 'Resume Ticket')
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

    # ─────────────────────────────────────────────────────────────────────────
    # Client reopen flow
    # ─────────────────────────────────────────────────────────────────────────

    def action_reopen_by_client(self, reason):
        """Reopen a Closed ticket on behalf of the client (called from the
        public portal reopen controller). Runs with elevated rights so it can
        reassign / touch fields normally locked to internal roles."""
        self.ensure_one()
        if self.stage_id.name != 'Closed':
            raise UserError('Only closed tickets can be reopened.')
        stage = self.env['client.helpdesk.stage'].search([('name', '=', 'Reopened')], limit=1)
        if not stage:
            raise UserError('The "Reopened" stage is not configured. Please contact support.')

        vals = {'stage_id': stage.id}
        if not self.user_id:
            admin = self._get_helpdesk_admin_user()
            if admin:
                vals['user_id'] = admin.id
        # write() already fires _notify_stage_change() for any stage_id
        # change, and 'Reopened' is one of STAGES_NOTIFYING_CLIENT_AND_STAFF
        # — so this one write() covers Client + Assigned User + Manager
        # without a separate reopen-specific notification method.
        self.sudo().with_context(
            helpdesk_close_reason=reason,
            helpdesk_close_action_type='reopen',
        ).write(vals)

        self.env['client.helpdesk.reason.line'].sudo().create({
            'ticket_id': self.id,
            'action_type': 'reopen',
            'reason': reason or '',
        })

        reason_safe = _html.escape(reason or '').replace('\n', '<br/>')
        self.sudo().message_post(
            body=Markup(f'<p><strong>Reopened by Client</strong></p><p>{reason_safe}</p>'),
            subject='Ticket Reopened by Client',
        )

        # Dedicated event_type='reopen' row — separate from the generic
        # 'email' rows _notify_stage_change() already logs for this same
        # reopen (Client/Assigned User/Manager notifications), so the
        # Notifications screen can filter "which tickets were reopened
        # and when" directly instead of inferring it from email subjects.
        self.env['client.helpdesk.notification.log'].sudo().create({
            'ticket_id': self.id,
            'event_type': 'reopen',
            'date_time': fields.Datetime.now(),
            'email_from': '',
            'email_to': self.email or '',
            'recipient_label': 'Client',
            'subject': f'Ticket {self.ticket_number} reopened by client — {reason or "(no reason given)"}',
        })
