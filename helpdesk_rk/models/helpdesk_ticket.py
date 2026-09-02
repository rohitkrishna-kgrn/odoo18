import re
import logging
from collections import defaultdict
from datetime import timedelta
from markupsafe import Markup
from odoo import api, fields, models, tools, Command
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# How long the author of a ticket-chat message may still edit or delete it.
CHAT_EDIT_WINDOW_MINUTES = 10

class HelpdeskTicket(models.Model):
    _name = 'helpdesk_rk.ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Helpdesk Ticket'
    _order = 'id desc'

    STAGE_SELECTION = [
        ('draft', 'Draft'),
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
    ]

    name = fields.Char('Subject', required=True, tracking=True)
    description = fields.Text('Description', tracking=True)
    ticket_number = fields.Char('Ticket Number', readonly=True, copy=False, index=True)
    deadline_date = fields.Date('Deadline Date', tracking=True)
    assigned_user_id = fields.Many2one(
        'res.users', string='Assigned To', tracking=True,
        domain=lambda self: [('groups_id', 'in', self.env.ref('helpdesk_rk.group_helpdesk_support').ids)]
        if self.env.ref('helpdesk_rk.group_helpdesk_support', raise_if_not_found=False) else [],
    )
    stage_id = fields.Selection(STAGE_SELECTION, string='Stage', default='draft', tracking=True, required=True,
                                 index=True, group_expand='_group_expand_stage_id')
    user_id = fields.Many2one('res.users', 'Created By', default=lambda self: self.env.user)
    email_to = fields.Char('Assigned Team Email', readonly=True)
    mail_message_id = fields.Many2one('mail.message', string="Original Email")
    attachment = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="Attachment Filename")
    active = fields.Boolean(default=True)
    favorite_user_ids = fields.Many2many('res.users', 'helpdesk_ticket_favorite_user_rel',
                                          'ticket_id', 'user_id', string='Favorited By', copy=False)
    is_favorite = fields.Boolean(string='Favorite', compute='_compute_is_favorite',
                                  inverse='_inverse_is_favorite', search='_search_is_favorite')
    is_support_team = fields.Boolean(compute='_compute_is_support_team')
    attachment_is_image = fields.Boolean(compute='_compute_attachment_kind')
    attachment_is_pdf = fields.Boolean(compute='_compute_attachment_kind')
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue', search='_search_is_overdue')
    unread_count = fields.Integer(string='Unread Messages', compute='_compute_unread_count')

    def _group_expand_stage_id(self, stages, domain):
        """Always show every stage as a Kanban/List group-by column, Draft
        first, even when a stage currently has no tickets - so Draft is the
        default column a user lands on. The All Tickets kanban excludes
        drafts entirely (support/admin view), so it flags the context to
        drop 'draft' from the forced columns instead of showing it empty."""
        keys = [key for key, _label in self.STAGE_SELECTION]
        if self.env.context.get('hide_draft_group'):
            keys.remove('draft')
        return keys

    @api.depends_context('uid')
    def _compute_is_support_team(self):
        for rec in self:
            rec.is_support_team = rec._check_user_in_support_team()

    @api.depends_context('uid')
    @api.depends('favorite_user_ids')
    def _compute_is_favorite(self):
        for rec in self:
            rec.is_favorite = self.env.user in rec.favorite_user_ids

    def _inverse_is_favorite(self):
        for rec in self:
            if self.env.user in rec.favorite_user_ids:
                rec.favorite_user_ids = [(3, self.env.uid)]
            else:
                rec.favorite_user_ids = [(4, self.env.uid)]

    def _search_is_favorite(self, operator, value):
        if operator != '=':
            raise NotImplementedError()
        domain = [('favorite_user_ids', 'in', [self.env.uid])]
        return domain if value else ['!'] + domain

    @api.depends('deadline_date', 'stage_id')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(
                rec.deadline_date
                and rec.deadline_date < today
                and rec.stage_id not in ('draft', 'done', 'rejected')
            )

    def _search_is_overdue(self, operator, value):
        if operator != '=':
            raise NotImplementedError()
        today = fields.Date.context_today(self)
        overdue_domain = [
            ('deadline_date', '!=', False),
            ('deadline_date', '<', today),
            ('stage_id', 'not in', ('draft', 'done', 'rejected')),
        ]
        if value:
            return overdue_domain
        return ['|', '|',
                ('deadline_date', '=', False),
                ('deadline_date', '>=', today),
                ('stage_id', 'in', ('draft', 'done', 'rejected'))]

    @api.depends_context('uid')
    @api.depends('message_ids', 'stage_id')
    def _compute_unread_count(self):
        chat_subtype = self.env.ref('helpdesk_rk.mt_ticket_chat', raise_if_not_found=False)
        if not chat_subtype:
            self.unread_count = 0
            return

        open_tickets = self.filtered(lambda t: t.stage_id not in ('draft', 'done', 'rejected'))
        (self - open_tickets).unread_count = 0
        if not open_tickets:
            return

        reads = self.env['helpdesk_rk.ticket.chat.read'].sudo().search([
            ('ticket_id', 'in', open_tickets.ids), ('user_id', '=', self.env.uid),
        ])
        last_read_by_ticket = {read.ticket_id.id: read.last_read_date for read in reads}

        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'helpdesk_rk.ticket'),
            ('res_id', 'in', open_tickets.ids),
            ('subtype_id', '=', chat_subtype.id),
        ])
        messages_by_ticket = defaultdict(list)
        for message in messages:
            messages_by_ticket[message.res_id].append(message)

        for rec in open_tickets:
            last_read = last_read_by_ticket.get(rec.id)
            count = 0
            for message in messages_by_ticket.get(rec.id, []):
                if last_read and message.date and message.date <= last_read:
                    continue
                # Compare partners, not users: res.partner.user_ids is
                # active_test'd, so an archived author resolves to no user at
                # all and the reader ends up counting their OWN messages as
                # unread. This is also exactly how _format_chat_message
                # decides `is_own`, so the bell and the bubbles now agree.
                if message.author_id and message.author_id.id == self.env.user.partner_id.id:
                    continue
                count += 1
            rec.unread_count = count

    def mark_chat_read(self):
        self.ensure_one()
        Read = self.env['helpdesk_rk.ticket.chat.read'].sudo()
        now = fields.Datetime.now()
        existing = Read.search([('ticket_id', '=', self.id), ('user_id', '=', self.env.uid)], limit=1)
        if existing:
            existing.last_read_date = now
        else:
            Read.create({'ticket_id': self.id, 'user_id': self.env.uid, 'last_read_date': now})

    @api.depends('attachment_filename')
    def _compute_attachment_kind(self):
        image_ext = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')
        for rec in self:
            name = (rec.attachment_filename or '').lower()
            rec.attachment_is_image = name.endswith(image_ext)
            rec.attachment_is_pdf = name.endswith('.pdf')

    @api.constrains('deadline_date')
    def _check_deadline_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.deadline_date and rec.deadline_date < today:
                raise ValidationError("Deadline Date cannot be earlier than the current date.")

    @api.constrains('assigned_user_id')
    def _check_assigned_user_in_support_team(self):
        support_group = self.env.ref('helpdesk_rk.group_helpdesk_support', raise_if_not_found=False)
        for rec in self:
            if rec.assigned_user_id and support_group and rec.assigned_user_id not in support_group.users:
                raise ValidationError("Assigned To must be a member of the Helpdesk Support Team.")

    def _get_support_team_emails(self):
        users = self.env.ref('helpdesk_rk.group_helpdesk_support').users
        emails = [email for email in users.mapped('email') if email]
        return ','.join(emails) or False

    @api.model
    def default_get(self, fields_list):
        """A new ticket must always open on Draft, even if the client asked
        for a different stage via context (e.g. clicking "+" inside a
        specific Kanban column injects default_stage_id for that column)."""
        defaults = super().default_get(fields_list)
        if 'stage_id' in fields_list:
            defaults['stage_id'] = 'draft'
        return defaults

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'deadline_date' in vals:
                raise UserError('Deadline Date can only be set or modified while the ticket is New or In Progress.')
            # A ticket must never start out favorited; favoriting is only
            # ever a deliberate action on an already-created ticket.
            vals.pop('favorite_user_ids', None)
            # Every ticket starts as a Draft: no ticket number, no emails,
            # no support-workflow visibility until explicitly submitted via
            # action_submit_ticket().
            vals['stage_id'] = 'draft'
            vals['ticket_number'] = False
            vals['email_to'] = False
        return super().create(vals_list)

    def action_submit_ticket(self):
        """Turn a Draft ticket into a real, actionable ticket: assign its
        number, move it to New, and only now run everything that makes it
        visible to the support workflow (emails, live kanban/list update)."""
        self.ensure_one()
        if self.stage_id != 'draft':
            raise UserError("This ticket has already been submitted.")
        if self.env.uid != self.user_id.id and not self._check_user_in_support_team():
            raise UserError("Not authorized.")
        if not self.name or not self.name.strip():
            raise UserError("Please enter a Subject before submitting the ticket.")
        self.write({
            'stage_id': 'new',
            'ticket_number': self.env['ir.sequence'].next_by_code('helpdesk_rk.ticket') or 'TCKT00001',
            'email_to': self._get_support_team_emails() or '',
            # A submitted ticket must always start Not Favorite, even if it
            # was starred while still a Draft.
            'favorite_user_ids': [(5, 0, 0)],
        })
        self._send_stage_email('New', to_support=True)
        self._send_stage_email('New', to_support=False)
        self._notify_ticket_submitted()

    def _notify_ticket_submitted(self):
        """Push the newly-submitted ticket to support/admin sessions so it
        appears live in their Kanban/List views without a page refresh."""
        self.ensure_one()
        for xmlid in ('helpdesk_rk.group_helpdesk_support', 'base.group_system'):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                self.env['bus.bus']._sendone(group, 'helpdesk_rk_ticket_created', {'ticket_id': self.id})

    def _notify_ticket_stage_changed(self):
        """Push a stage change to every session that might be showing this
        ticket, so it updates live with no page refresh:
        - the ticket's own channel, for whoever (user or support) has this
          exact ticket's form open - refreshes the statusbar, buttons and
          the chat's read-only/composer state together;
        - the creator's own partner channel (always implicitly subscribed
          for a logged-in user), so their "My Tickets" board updates;
        - the support/admin groups, so the "All Tickets" board updates.
        """
        self.ensure_one()
        self.env['bus.bus']._sendone(
            f'helpdesk_rk.ticket_chat_{self.id}',
            'helpdesk_rk_ticket_updated',
            {'ticket_id': self.id, 'stage_id': self.stage_id},
        )
        if self.user_id.partner_id:
            self.env['bus.bus']._sendone(
                self.user_id.partner_id, 'helpdesk_rk_ticket_updated', {'ticket_id': self.id},
            )
        for xmlid in ('helpdesk_rk.group_helpdesk_support', 'base.group_system'):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                self.env['bus.bus']._sendone(group, 'helpdesk_rk_ticket_updated', {'ticket_id': self.id})

    def write(self, vals):
        if 'assigned_user_id' in vals:
            if not self._check_user_in_support_team():
                raise UserError("You are not allowed to set or edit the Assigned To field.")
        if 'deadline_date' in vals:
            if not self._check_user_in_support_team():
                raise UserError("You are not allowed to set or edit the Deadline Date.")
            for rec in self:
                if vals.get('stage_id', rec.stage_id) not in ('new', 'in_progress'):
                    raise UserError('Deadline Date can only be set or modified while the ticket is New or In Progress.')
                if rec.is_overdue and not self.env.context.get('helpdesk_deadline_reason_confirmed'):
                    raise UserError(
                        "This ticket's Deadline Date is overdue. Please use the 'Change Deadline' "
                        "button to provide a reason before updating it."
                    )
        if vals.get('stage_id') in ('done', 'rejected'):
            for rec in self:
                if not vals.get('deadline_date', rec.deadline_date):
                    raise UserError(
                        f'Please set the Deadline Date before changing the ticket status to "{dict(self.STAGE_SELECTION).get(vals["stage_id"])}".'
                    )
        if set(vals.keys()) - {'favorite_user_ids'}:
            for rec in self:
                if rec.stage_id in ('done', 'rejected'):
                    raise ValidationError("You cannot modify a ticket that is Done or Rejected.")
        stage_changed = self.browse()
        if 'stage_id' in vals:
            stage_changed = self.filtered(lambda r: r.stage_id != vals['stage_id'])
        result = super().write(vals)
        for rec in stage_changed:
            rec._notify_ticket_stage_changed()
        return result

    def _send_stage_email(self, stage_name, to_support=False):
        company = self.env.user.company_id
        logo_url = "https://kompanyservices.com/wp-content/uploads/logo-kgrn.png"
        support_email = self._get_support_team_emails() or 'support@yourcompany.com'
        company_name = company.name or "Your Company"
        year = fields.Date.today().year

        if to_support:
            email_to = support_email
            subject = f"[Helpdesk] New Ticket #{self.ticket_number}: {self.name}"
            email_heading = "New Helpdesk Ticket Submitted"
            email_message = "A new helpdesk ticket has been submitted by a user. Please review and take action."
            ticket_url = '#'
        else:
            if not self.user_id.email:
                _logger.warning(f"User email missing for ticket {self.ticket_number}")
                return
            email_to = self.user_id.email
            subject = f"Thank You - Helpdesk Ticket #{self.ticket_number} Received"
            email_heading = "Thank You for Contacting Support"
            email_message = "Your support request has been received. Our team will review it and get back to you shortly."

        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Ticket Email</title></head>
<body style="margin:0;padding:0;background:#f4f6f9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;font-family:Arial,sans-serif;">
<tr><td align="center">
  <table width="700" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e1e4e8;border-radius:8px;margin:20px 0;">
    <tr><td style="background:#003366;padding:20px;text-align:center;">
      <img src="{logo_url}" alt="Logo" width="100" height="100" style="display:block;margin:0 auto;border:0;" />
    </td></tr>
    <tr><td style="padding:40px 30px;">
      <h1 style="color:#003366;font-size:20px;margin:0 0 20px;">{email_heading}</h1>
      <table width="100%" cellpadding="0" cellspacing="0"><tr><td>
        <table width="100%" cellpadding="0" cellspacing="0" style="padding:0 0 20px 0;">
          <tr><td style="font-size:15px;color:#333;line-height:1.6;">{email_message}</td></tr>
        </table>
      </td></tr></table>

      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f6ff;border-left:5px solid #004080;">
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Ticket #:</strong>{self.ticket_number}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Subject:</strong>{self.name}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Status:</strong>{stage_name.replace('_',' ').title()}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Description:</strong>{self.description or '-'}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Submitted By:</strong>{self.user_id.name}</td></tr>
      </table>

    </td></tr>
    <tr><td style="background:#fafbfc;text-align:center;font-size:13px;color:#888;padding:20px;">
      &copy; {year} {company_name}. For assistance, <a href="mailto:{support_email}" style="color:#888;">{support_email}</a>
    </td></tr>
  </table>
</td></tr></table>
</body>
</html>
"""
        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_to': email_to,
            'author_id': self.env.user.partner_id.id,
            'model': self._name,
            'res_id': self.id,
        }
        try:
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.sudo().send()
            _logger.info(f"Email sent for ticket #{self.ticket_number} to {email_to}")
        except Exception as e:
            _logger.error(f"Failed to send email for ticket #{self.ticket_number}: {e}")

    def _check_user_in_support_team(self, user=None):
        user = user or self.env.user
        return user.has_group('base.group_system') or user.has_group('helpdesk_rk.group_helpdesk_support')

    # ------------------------------------------------------------
    # Ticket Conversation (Discuss-style chat)
    # ------------------------------------------------------------

    def _can_post_chat_message(self, user=None):
        """Only the ticket creator or a member of the Helpdesk Support Team
        may post, and only while the ticket is New or In Progress."""
        self.ensure_one()
        user = user or self.env.user
        if self.stage_id not in ('new', 'in_progress'):
            return False
        return user.id == self.user_id.id or self._check_user_in_support_team(user)

    def _can_access_chat(self, user=None):
        """Who may read this ticket's conversation and download the files
        shared in it: the creator, the agent it is assigned to, and the
        Helpdesk Support Team / admins. Used by the chat attachment
        controller, which browses in sudo and so must check by hand."""
        self.ensure_one()
        user = user or self.env.user
        return (
            user.id == self.user_id.id
            or (self.assigned_user_id and user.id == self.assigned_user_id.id)
            or self._check_user_in_support_team(user)
        )

    def _get_chat_author_role(self, partner):
        user = partner.user_ids[:1] if partner else self.env['res.users']
        if not user:
            return 'External'
        if user.id == self.user_id.id:
            return 'Ticket Creator'
        if self._check_user_in_support_team(user):
            return 'Helpdesk Support Team'
        return 'Staff'

    def _format_chat_attachment(self, attachment):
        """Both sides of the conversation download through our own route
        (see HelpdeskChatController.chat_attachment) instead of /web/content:
        the file itself only ever carries res_model/res_id of the ticket, so
        the route is what decides that the other party may read it - no
        public access token has to be minted on the attachment."""
        return {
            'id': attachment.id,
            'name': attachment.name,
            'mimetype': attachment.mimetype,
            'size': attachment.file_size,
            'is_image': (attachment.mimetype or '').startswith('image/'),
            'url': f'/helpdesk_rk/chat/attachment/{attachment.id}',
            'download_url': f'/helpdesk_rk/chat/attachment/{attachment.id}?download=1',
        }

    def _format_chat_message(self, message):
        author = message.author_id
        is_own = bool(author and author.id == self.env.user.partner_id.id)
        # Seconds still left on the edit/delete window, measured on the
        # server. The browser counts this down from the moment the thread was
        # loaded, so a wrong clock on the client cannot re-open the window -
        # and update/delete re-check it server-side anyway.
        seconds_left = 0
        if is_own and message.date and self.stage_id in ('new', 'in_progress'):
            deadline = message.date + timedelta(minutes=CHAT_EDIT_WINDOW_MINUTES)
            seconds_left = max((deadline - fields.Datetime.now()).total_seconds(), 0)
        return {
            'id': message.id,
            'author_name': author.name if author else (message.email_from or 'Unknown'),
            'author_role': self._get_chat_author_role(author) if author else 'External',
            'body': tools.html2plaintext(message.body) if message.body else '',
            'date': fields.Datetime.to_string(fields.Datetime.context_timestamp(self, message.date)),
            'is_own': is_own,
            'edited': bool(message.helpdesk_chat_edited),
            'editable_seconds_left': seconds_left,
            'attachments': [
                self._format_chat_attachment(attachment)
                for attachment in message.sudo().attachment_ids
            ],
        }

    def _get_chat_other_party(self):
        """Who's on the other end of this ticket's conversation, from the
        current viewer's point of view: support/admin sees the ticket
        creator, everyone else sees the currently assigned support agent
        (or nothing, if no one has been assigned yet). Used to render a
        Discuss-DM-style header (name, avatar, live presence)."""
        self.ensure_one()
        if self._check_user_in_support_team():
            other_user, role = self.user_id, 'Ticket Creator'
        else:
            other_user, role = self.assigned_user_id, 'Helpdesk Support Team'
        if not other_user:
            return {
                'user_id': False,
                'partner_id': False,
                'name': False,
                'role': False,
                'im_status': False,
            }
        return {
            'user_id': other_user.id,
            'partner_id': other_user.partner_id.id,
            'name': other_user.name,
            'role': role,
            'im_status': other_user.im_status,
        }

    def _get_chat_messages(self):
        self.ensure_one()
        chat_subtype = self.env.ref('helpdesk_rk.mt_ticket_chat')
        return self.message_ids.filtered(
            lambda m: m.subtype_id.id == chat_subtype.id
        ).sorted('date')

    def get_chat_thread_data(self, mark_read=True):
        """`mark_read` is False while the chat panel sits folded: the
        messages are fetched so the panel can show an unread badge, but the
        user has not actually seen them yet, so the bell must keep ringing."""
        self.ensure_one()
        data = {
            'can_post': self._can_post_chat_message(),
            'is_closed': self.stage_id in ('done', 'rejected'),
            'edit_window_minutes': CHAT_EDIT_WINDOW_MINUTES,
            # Feeds the badge on the folded launcher; same number the kanban
            # and list bells show, so the two never disagree.
            'unread_count': self.unread_count,
            'messages': [self._format_chat_message(message) for message in self._get_chat_messages()],
            'other_party': self._get_chat_other_party(),
        }
        if mark_read:
            self.mark_chat_read()
        return data

    def _notify_chat_changed(self):
        """Wake every session showing this ticket (its chat panel, and the
        bell on the kanban/list boards) so a new, edited or deleted message
        shows up without a refresh."""
        self.ensure_one()
        self.env['bus.bus']._sendone(
            f'helpdesk_rk.ticket_chat_{self.id}',
            'helpdesk_rk_chat_message',
            {'ticket_id': self.id},
        )

    def _get_chat_notified_partner(self):
        """The single person a new chat message is announced to, as a toast
        in the corner of whatever page they are on:

          * written by the Helpdesk Support Team -> the ticket creator;
          * written by the ticket creator -> the agent the ticket is
            assigned to, and nobody at all while it is still unassigned.

        Never the author themselves, and never a broadcast to the whole
        support team."""
        self.ensure_one()
        author = self.env.user
        if author.id == self.user_id.id:
            target = self.assigned_user_id
        elif self._check_user_in_support_team(author):
            target = self.user_id
        else:
            target = self.env['res.users']
        if not target or target.id == author.id:
            return self.env['res.partner']
        return target.partner_id

    def _notify_chat_message_to_recipient(self, message):
        self.ensure_one()
        partner = self._get_chat_notified_partner()
        if not partner:
            return
        preview = tools.html2plaintext(message.body).strip() if message.body else ''
        if not preview:
            count = len(message.attachment_ids)
            preview = f"Sent {count} attachment(s)." if count else ''
        if len(preview) > 150:
            preview = preview[:150] + '...'
        self.env['bus.bus']._sendone(partner, 'helpdesk_rk_chat_notification', {
            'ticket_id': self.id,
            'message_id': message.id,
            'ticket_number': self.ticket_number or '',
            'ticket_name': self.name or '',
            'author_name': self.env.user.name,
            'author_role': self._get_chat_author_role(self.env.user.partner_id),
            'preview': preview,
        })

    def _link_pending_chat_attachments(self, attachment_ids):
        """Attachments are uploaded before the message exists, parked on
        'mail.compose.message'/res_id 0 by the upload route. Only the ones
        this very user parked there may be pulled into a message."""
        self.ensure_one()
        if not attachment_ids:
            return self.env['ir.attachment']
        return self.env['ir.attachment'].sudo().browse(attachment_ids).exists().filtered(
            lambda a: a.res_model == 'mail.compose.message'
            and not a.res_id
            and a.create_uid.id == self.env.uid
        )

    def post_chat_message(self, body, attachment_ids=None):
        self.ensure_one()
        if not self._can_post_chat_message():
            raise UserError("You are not allowed to post messages on this ticket.")
        body = (body or '').strip()
        attachments = self._link_pending_chat_attachments([int(a) for a in (attachment_ids or [])])
        if not body and not attachments:
            raise UserError("Cannot send an empty message.")
        # message_post() only accepts attachments still parked on the
        # composer *and created by the acting user* - which is exactly what
        # _link_pending_chat_attachments already guaranteed.
        message = self.with_context(mail_create_nosubscribe=True).message_post(
            body=tools.plaintext2html(body) if body else '',
            message_type='comment',
            subtype_id=self.env.ref('helpdesk_rk.mt_ticket_chat').id,
            attachment_ids=attachments.ids,
        )
        self._notify_chat_changed()
        self._notify_chat_message_to_recipient(message)
        return self.get_chat_thread_data()

    def _get_own_editable_chat_message(self, message_id):
        """A message may only be touched by the person who wrote it, on an
        open ticket, and only inside the CHAT_EDIT_WINDOW_MINUTES window
        after it was sent. Checked here on every edit and delete, so a stale
        browser tab cannot slip an edit through after the window closed."""
        self.ensure_one()
        chat_subtype = self.env.ref('helpdesk_rk.mt_ticket_chat')
        message = self.env['mail.message'].sudo().browse(int(message_id)).exists()
        if (not message or message.model != self._name or message.res_id != self.id
                or message.subtype_id.id != chat_subtype.id):
            raise UserError("This message does not belong to this ticket's conversation.")
        if not message.author_id or message.author_id.id != self.env.user.partner_id.id:
            raise UserError("You can only edit or delete the messages you sent.")
        if self.stage_id not in ('new', 'in_progress'):
            raise UserError("This ticket is closed, its conversation can no longer be changed.")
        deadline = message.date + timedelta(minutes=CHAT_EDIT_WINDOW_MINUTES)
        if fields.Datetime.now() > deadline:
            raise UserError(
                f"Messages can only be edited or deleted within {CHAT_EDIT_WINDOW_MINUTES} "
                "minutes of being sent."
            )
        return message

    def update_chat_message(self, message_id, body, attachment_ids=None):
        """Rewrite one of my own messages: `attachment_ids` is the full list
        the message should end up with - the ones kept out of it are deleted,
        ids not on the message yet are freshly uploaded ones to pull in."""
        self.ensure_one()
        message = self._get_own_editable_chat_message(message_id)
        body = (body or '').strip()
        wanted_ids = {int(a) for a in (attachment_ids or [])}
        existing = message.attachment_ids
        kept = existing.filtered(lambda a: a.id in wanted_ids)
        dropped = existing - kept
        added = self._link_pending_chat_attachments(list(wanted_ids - set(existing.ids)))
        if not body and not kept and not added:
            raise UserError("A message cannot be left empty. Delete it instead.")
        if added:
            added.write({'res_model': self._name, 'res_id': self.id})
        message.write({
            'body': tools.plaintext2html(body) if body else '',
            'attachment_ids': [Command.set((kept | added).ids)],
            'helpdesk_chat_edited': True,
        })
        if dropped:
            dropped.unlink()
        self._notify_chat_changed()
        return self.get_chat_thread_data()

    def delete_chat_message(self, message_id):
        self.ensure_one()
        message = self._get_own_editable_chat_message(message_id)
        # mail.message.unlink() only cascades attachments still parked on
        # 'mail.message'; ours were moved onto the ticket when they were
        # posted, so they have to be dropped by hand or they leak.
        attachments = message.attachment_ids
        message.unlink()
        if attachments:
            attachments.unlink()
        self._notify_chat_changed()
        return self.get_chat_thread_data()

    def action_set_in_progress(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        if not self.deadline_date:
            raise UserError("Please set the Deadline Date before moving the ticket to the 'In Progress' stage.")
        if not self.assigned_user_id:
            raise UserError("Please set the Assigned To field before moving the ticket to the 'In Progress' stage.")
        self.stage_id = 'in_progress'

    def action_set_done(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        if not self.deadline_date:
            raise UserError('Please set the Deadline Date before changing the ticket status to "Done".')
        self.stage_id = 'done'

    def action_set_rejected(self, reason=None):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        if not self.deadline_date:
            raise UserError('Please set the Deadline Date before changing the ticket status to "Rejected".')
        self.stage_id = 'rejected'
        if reason:
            self.message_post(
                body=f"Ticket Status changed to Rejected.\nReason/Remarks: {reason}",
                subtype_xmlid='mail.mt_note',
            )

    def action_open_reject_wizard(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        return {
            'name': 'Reject Ticket',
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk_rk.ticket.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id},
        }

    def action_open_deadline_wizard(self):
        self.ensure_one()
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        if not self.is_overdue:
            raise UserError("This ticket's Deadline Date is not overdue.")
        return {
            'name': 'Change Deadline',
            'type': 'ir.actions.act_window',
            'res_model': 'helpdesk_rk.ticket.deadline.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_ticket_id': self.id},
        }

    def action_change_overdue_deadline(self, new_deadline_date, reason):
        self.ensure_one()
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        if not self.is_overdue:
            raise UserError("This ticket's Deadline Date is not overdue.")
        if not new_deadline_date:
            raise UserError("Please select the new Deadline Date.")
        if not reason or not reason.strip():
            raise UserError("Please enter the reason for changing the overdue deadline.")
        old_deadline_date = self.deadline_date
        self.with_context(helpdesk_deadline_reason_confirmed=True).write({'deadline_date': new_deadline_date})
        self._post_overdue_deadline_change(old_deadline_date, new_deadline_date, reason.strip())

    def _post_overdue_deadline_change(self, old_deadline_date, new_deadline_date, reason):
        self.ensure_one()
        old_str = fields.Date.to_string(old_deadline_date) if old_deadline_date else '-'
        new_str = fields.Date.to_string(new_deadline_date) if new_deadline_date else '-'
        body = Markup(
            '<div style="padding:12px 16px;background:#fff4e5;border-left:5px solid #e67e22;'
            'border-radius:6px;margin:4px 0;">'
            '<div style="font-weight:700;color:#e67e22;font-size:13px;text-transform:uppercase;'
            'letter-spacing:.03em;margin-bottom:6px;">&#9888; Overdue Deadline Changed</div>'
            '<div style="font-size:14px;color:#333;line-height:1.6;">'
            '<strong>Previous Deadline:</strong> %(old)s<br/>'
            '<strong>New Deadline:</strong> %(new)s<br/>'
            '<strong>Reason:</strong> %(reason)s'
            '</div></div>'
        ) % {'old': old_str, 'new': new_str, 'reason': reason}
        self.message_post(body=body, subtype_xmlid='mail.mt_note')
