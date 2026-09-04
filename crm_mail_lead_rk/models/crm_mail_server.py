# -*- coding: utf-8 -*-
"""CRM-owned incoming mail server.

Deliberately *not* an inherit of ``fetchmail.server``: the standard incoming
mail servers feed Odoo's mail gateway (aliases, chatter, document creation),
and mixing this in would either hijack those mailboxes or expose CRM staff to
the technical settings. This model owns its own IMAP connection, its own cron
and its own polling window, and it only ever writes ``crm.mail.lead`` records.
"""
import email
import email.policy
import imaplib
import logging
import socket

from datetime import timedelta
from imaplib import IMAP4
from ssl import SSLError

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MAIL_TIMEOUT = 60

# IMAP SEARCH only understands English month abbreviations, while
# ``strftime('%b')`` follows the process locale — build the literal by hand.
IMAP_MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')

# Hard stop on a single fetch, so a mailbox that has been unread for weeks
# cannot flood the pipeline in one cron beat.
MAX_MESSAGES_PER_FETCH = 100


class CrmMailServer(models.Model):
    _name = 'crm.mail.server'
    _description = 'CRM Incoming Mail Server'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name', required=True,
        help="Label shown in CRM, e.g. \"DM Inbox\" or \"Einvoicing Inbox\".")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    tag_id = fields.Many2one(
        'crm.tag', string='Mail Lead Tag', required=True, ondelete='restrict',
        help="Tag stamped on every mail pulled from this inbox, so you can tell "
             "at a glance which mailbox a Mail Lead came from. It is also copied "
             "onto the CRM pipeline record created on assignment.")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    server = fields.Char(
        string='Server', required=True, default='imap.gmail.com',
        help="IMAP host name. For Gmail / Google Workspace: imap.gmail.com")
    port = fields.Integer(string='Port', required=True, default=993)
    is_ssl = fields.Boolean(
        string='SSL/TLS', default=True,
        help="Connect through a dedicated encrypted port (Gmail IMAPS = 993).")
    user = fields.Char(
        string='Username', required=True,
        help="Full Gmail address, e.g. dm@yourdomain.com")
    password = fields.Char(
        string='Password',
        help="Google no longer accepts account passwords over IMAP: generate a "
             "16-character App Password (Google Account > Security > 2-Step "
             "Verification > App passwords) and paste it here.")
    folder = fields.Char(
        string='Mailbox Folder', default='INBOX', required=True,
        help="IMAP folder to poll. Leave INBOX unless mail is filtered into a "
             "label — for a Gmail label use e.g. \"MyLabel\".")

    state = fields.Selection(
        [('draft', 'Not Confirmed'), ('done', 'Confirmed')],
        string='Status', default='draft', readonly=True, copy=False, required=True)

    # ------------------------------------------------------------------
    # Polling window
    # ------------------------------------------------------------------
    fetch_window_minutes = fields.Integer(
        string='Fetch Window (minutes)', default=5, required=True,
        help="On the very first run, how far back to look. Afterwards the "
             "server only picks up mail that arrived since the previous run.")
    max_lookback_hours = fields.Integer(
        string='Max Lookback (hours)', default=24, required=True,
        help="Safety cap: if the cron has been stopped for a long time, never "
             "reach further back than this when it starts again.")
    mark_as_read = fields.Boolean(
        string='Mark as Read in Mailbox', default=False,
        help="Flag each pulled mail as read in Gmail. Left off, the mailbox is "
             "untouched — duplicates are prevented by the message id instead.")
    keep_attachments = fields.Boolean(
        string='Keep Attachments', default=True,
        help="Download attachments and carry them onto the pipeline record.")

    last_fetch_date = fields.Datetime(string='Last Fetch', readonly=True, copy=False)
    last_error = fields.Text(string='Last Error', readonly=True, copy=False)

    mail_lead_ids = fields.One2many('crm.mail.lead', 'server_id', string='Mail Leads')
    mail_lead_count = fields.Integer(compute='_compute_mail_lead_count')

    _sql_constraints = [
        # "user" is a reserved SQL keyword — unquoted, Postgres reads it as the
        # current_user function and silently refuses the constraint.
        ('user_uniq', 'unique("user", company_id)',
         'An incoming CRM mail server already exists for this mailbox.'),
        ('fetch_window_positive', 'CHECK(fetch_window_minutes > 0)',
         'The fetch window must be at least one minute.'),
        ('max_lookback_positive', 'CHECK(max_lookback_hours > 0)',
         'The maximum lookback must be at least one hour.'),
    ]

    @api.depends('mail_lead_ids')
    def _compute_mail_lead_count(self):
        counts = dict(self.env['crm.mail.lead']._read_group(
            [('server_id', 'in', self.ids)], ['server_id'], ['__count']))
        for server in self:
            server.mail_lead_count = counts.get(server, 0)

    @api.onchange('is_ssl')
    def _onchange_is_ssl(self):
        self.port = 993 if self.is_ssl else 143

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def button_confirm_login(self):
        """Test the credentials and move the server to Confirmed."""
        for server in self:
            connection = None
            try:
                connection = server._connect()
                typ, _data = connection.select(server.folder or 'INBOX')
                if typ != 'OK':
                    raise UserError(_(
                        "Connected, but the folder %(folder)s does not exist on "
                        "%(server)s.",
                        folder=server.folder, server=server.server))
                server.write({'state': 'done', 'last_error': False})
            except UserError:
                raise
            except UnicodeError as err:
                raise UserError(_("Invalid server name.\n%s", tools.exception_to_unicode(err)))
            except (socket.gaierror, socket.timeout, TimeoutError, IMAP4.abort) as err:
                raise UserError(_(
                    "No response from %(server)s:%(port)s. Check the host and port.\n%(err)s",
                    server=server.server, port=server.port,
                    err=tools.exception_to_unicode(err)))
            except SSLError as err:
                raise UserError(_(
                    "SSL error — check the SSL/TLS setting against the port.\n%s",
                    tools.exception_to_unicode(err)))
            except IMAP4.error as err:
                raise UserError(_(
                    "The mail server rejected the login:\n%(err)s\n\n"
                    "For Gmail this is almost always the password: a normal "
                    "account password is refused, you need a 16-character App "
                    "Password generated with 2-Step Verification enabled, and "
                    "IMAP must be turned on in Gmail settings.",
                    err=tools.exception_to_unicode(err)))
            except Exception as err:
                _logger.info("CRM mail server %s: connection test failed.", server.name, exc_info=True)
                raise UserError(_("Connection test failed: %s", tools.exception_to_unicode(err)))
            finally:
                self._safe_disconnect(connection)
        return True

    def button_set_draft(self):
        self.write({'state': 'draft'})
        return True

    def button_fetch_now(self):
        """Manual 'Fetch Now' — same code path as the cron, errors surfaced.

        Unlike the cron this ignores the rolling time window: it pulls every
        still-unread mail that has not been imported yet, so a message that was
        already sitting in the inbox when the mailbox was set up is picked up.
        """
        totals = self.fetch_mail(raise_exception=True, ignore_window=True)
        imported = totals.get('imported', 0)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if imported else 'info',
                'title': _("Mailbox checked"),
                'message': (
                    _("%s new mail lead(s) pulled into Mail Leads.", imported)
                    if imported else
                    _("No new unread mail — every message is already listed.")),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_view_mail_leads(self):
        self.ensure_one()
        return {
            'name': _("Mail Leads"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.mail.lead',
            'view_mode': 'list,form',
            'domain': [('server_id', '=', self.id)],
            'context': {'search_default_server_id': self.id},
        }

    # ------------------------------------------------------------------
    # IMAP plumbing
    # ------------------------------------------------------------------
    def _connect(self):
        self.ensure_one()
        if self.is_ssl:
            connection = imaplib.IMAP4_SSL(self.server, int(self.port), timeout=MAIL_TIMEOUT)
        else:
            connection = imaplib.IMAP4(self.server, int(self.port), timeout=MAIL_TIMEOUT)
        connection.login(self.user, self.password or '')
        return connection

    @staticmethod
    def _safe_disconnect(connection):
        if not connection:
            return
        try:
            connection.close()
        except Exception:  # noqa: BLE001 - the mailbox may already be gone
            pass
        try:
            connection.logout()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _imap_date(value):
        """IMAP ``SINCE`` literal (``dd-Mon-yyyy``) for a datetime."""
        return '%02d-%s-%04d' % (value.day, IMAP_MONTHS[value.month - 1], value.year)

    def _get_fetch_cutoff(self):
        """Oldest mail this run may pick up.

        First run looks back ``fetch_window_minutes``; later runs resume from the
        previous fetch (minus a minute of overlap so a mail that landed while the
        last run was in flight is not skipped — ``crm.mail.lead`` deduplicates on
        the message id, so the overlap cannot create doubles). The lookback is
        capped so a cron that was off for a month does not import a month of mail.
        """
        self.ensure_one()
        now = fields.Datetime.now()
        if self.last_fetch_date:
            cutoff = self.last_fetch_date - timedelta(seconds=60)
        else:
            cutoff = now - timedelta(minutes=self.fetch_window_minutes or 5)
        return max(cutoff, now - timedelta(hours=self.max_lookback_hours or 24))

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------
    @api.model
    def _cron_fetch_mail(self):
        """Entry point of the every-2-minutes cron."""
        servers = self.search([('state', '=', 'done')])
        for server in servers:
            # One bad mailbox must not stop the others, and the mails already
            # imported by an earlier server stay imported.
            try:
                server.fetch_mail(raise_exception=True, commit=True)
                self.env.cr.commit()
            except Exception as err:  # noqa: BLE001 - cron must survive anything
                self.env.cr.rollback()
                _logger.warning(
                    "CRM mail server %s: fetch failed.", server.name, exc_info=True)
                server.sudo().write({'last_error': tools.exception_to_unicode(err)})
                self.env.cr.commit()
        return True

    def fetch_mail(self, raise_exception=True, commit=False, ignore_window=False):
        """Pull unread mail received since the last run into ``crm.mail.lead``.

        :param bool raise_exception: re-raise connection/parse failures instead
            of only logging them.
        :param bool commit: commit after each imported mail (cron usage only).
        :param bool ignore_window: pull *every* still-unread mail that has not
            been imported yet, not just the ones inside the rolling window used
            by the cron. Used by the manual 'Fetch Now' buttons. Deduplication
            is still on the message id, and ``MAX_MESSAGES_PER_FETCH`` still
            caps a single run.
        :return: aggregated counts across ``self``:
            ``{'imported': int, 'skipped': int, 'failed': int, 'errors': int}``.
        """
        MailLead = self.env['crm.mail.lead'].sudo()
        totals = {'imported': 0, 'skipped': 0, 'failed': 0, 'errors': 0}
        for server in self:
            connection = None
            if ignore_window:
                # Look all the way back; the real filter is "unread and not yet
                # imported", applied by IMAP UNSEEN + the message-id dedup.
                cutoff = fields.Datetime.now() - timedelta(days=3650)
            else:
                cutoff = server._get_fetch_cutoff()
            imported = skipped = failed = 0
            try:
                connection = server._connect()
                typ, _data = connection.select(server.folder or 'INBOX')
                if typ != 'OK':
                    raise UserError(_(
                        "Mailbox folder %(folder)s not found on %(server)s.",
                        folder=server.folder, server=server.server))

                # IMAP SINCE has day granularity only and compares against the
                # server's own clock, so widen by a day here and apply the real
                # cut-off below against each mail's own Date header.
                typ, data = connection.search(
                    None, 'UNSEEN', 'SINCE', server._imap_date(cutoff - timedelta(days=1)))
                if typ != 'OK':
                    raise UserError(_("IMAP search failed on %s.", server.name))

                nums = data[0].split() if data and data[0] else []
                if len(nums) > MAX_MESSAGES_PER_FETCH:
                    _logger.warning(
                        "CRM mail server %s: %d unread messages matched, importing "
                        "only the %d most recent this run; the rest follow on the "
                        "next cron beats.",
                        server.name, len(nums), MAX_MESSAGES_PER_FETCH)
                    nums = nums[-MAX_MESSAGES_PER_FETCH:]

                for num in nums:
                    # BODY.PEEK[] reads the message *without* setting \Seen, so
                    # an unassigned mail stays unread in the user's inbox unless
                    # 'Mark as Read in Mailbox' is on.
                    typ, msg_data = connection.fetch(num, '(BODY.PEEK[])')
                    if typ != 'OK':
                        failed += 1
                        continue
                    raw = next(
                        (part[1] for part in msg_data
                         if isinstance(part, tuple) and len(part) > 1),
                        None)
                    if not raw:
                        failed += 1
                        continue
                    try:
                        values = server._prepare_mail_lead_values(raw, cutoff)
                    except Exception:  # noqa: BLE001 - one unparseable mail
                        _logger.warning(
                            "CRM mail server %s: could not parse a message.",
                            server.name, exc_info=True)
                        failed += 1
                        continue
                    if not values:
                        skipped += 1
                        continue

                    attachments = values.pop('__attachments__', [])
                    mail_lead = MailLead.create(values)
                    if attachments:
                        mail_lead._store_attachments(attachments)
                    imported += 1

                    if server.mark_as_read:
                        connection.store(num, '+FLAGS', '\\Seen')
                    if commit:
                        self.env.cr.commit()

                server.sudo().write({
                    'last_fetch_date': fields.Datetime.now(),
                    'last_error': False,
                })
                _logger.info(
                    "CRM mail server %s: %d imported, %d skipped, %d failed.",
                    server.name, imported, skipped, failed)
            except Exception as err:  # noqa: BLE001
                if raise_exception:
                    raise
                totals['errors'] += 1
                _logger.warning(
                    "CRM mail server %s: fetch failed.", server.name, exc_info=True)
                server.sudo().write({'last_error': tools.exception_to_unicode(err)})
            finally:
                self._safe_disconnect(connection)
            totals['imported'] += imported
            totals['skipped'] += skipped
            totals['failed'] += failed
        return totals

    def _prepare_mail_lead_values(self, raw_message, cutoff):
        """Turn one raw RFC-2822 mail into ``crm.mail.lead`` values.

        Returns ``None`` when the mail must be ignored (older than the window,
        already imported, or a bounce).
        """
        self.ensure_one()
        message = email.message_from_bytes(raw_message, policy=email.policy.SMTP)
        parsed = self.env['mail.thread'].message_parse(message)

        if parsed.get('is_bounce'):
            return None

        message_id = (parsed.get('message_id') or '').strip()
        date_received = fields.Datetime.to_datetime(parsed.get('date')) or fields.Datetime.now()
        # The real "received in the last N minutes" test — IMAP's SINCE could
        # only narrow this down to the day.
        if date_received < cutoff:
            return None
        if message_id and self.env['crm.mail.lead'].sudo().search_count(
                [('server_id', '=', self.id), ('message_id', '=', message_id)], limit=1):
            return None

        email_from = parsed.get('email_from') or ''
        contact_name, email_address = tools.mail.parse_contact_from_email(email_from)

        values = {
            'name': parsed.get('subject') or _('(No Subject)'),
            'server_id': self.id,
            'company_id': self.company_id.id,
            'message_id': message_id or False,
            'email_from': email_address or email_from,
            'email_from_raw': email_from,
            'contact_name': contact_name or False,
            'email_to': parsed.get('to') or False,
            'email_cc': parsed.get('cc') or False,
            'date_received': date_received,
            'body': parsed.get('body') or False,
        }
        if self.keep_attachments:
            values['__attachments__'] = parsed.get('attachments') or []
        return values
