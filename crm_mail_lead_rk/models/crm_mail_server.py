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
import re
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

# 'Fetch Mails' (full import, read + unread): messages pulled per cron beat
# while a full import is in progress. Bounded so one beat cannot run long
# enough to overlap the next scheduled beat.
FULL_IMPORT_BATCH = 200

# Full import: UIDs fetched per single IMAP round-trip within a batch. A real
# IMAP round-trip to Gmail (login-free, already-connected) still costs real
# latency per call, so pulling BODY.PEEK[] for several messages at once is
# what keeps a 200-message batch fast enough to finish inside the cron
# interval instead of taking minutes one message at a time.
BODY_FETCH_CHUNK = 20

# 'Fetch Mails' button: messages imported synchronously in the click itself,
# so the user sees results right away; the same click also wakes the cron,
# which drains the rest of the mailbox automatically in the background.
FETCH_MAILS_SYNC_BATCH = 40

# Advisory-lock namespace: guarantees the button's synchronous batch and a
# cron beat never fetch the same mailbox at the same time (a second writer to
# the crm.mail.server row would otherwise hit a serialization error and Odoo
# would retry the whole call, re-fetching everything). Released automatically
# at the next commit/rollback.
FETCH_LOCK_NS = 0x43524D4C  # 'CRML'


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

    full_import_requested = fields.Boolean(
        string='Fetch Mails Running', default=False, readonly=True, copy=False,
        help="Set by the Fetch Mails button (CRM > Mail Leads). While on, "
             "every cron beat keeps pulling messages from this mailbox — read "
             "and unread, most recent first — until the whole folder has been "
             "imported, then this clears itself automatically.")
    full_import_floor_uid = fields.Integer(
        string='Fetch Mails Progress (UID floor)', default=0, readonly=True, copy=False,
        help="Every IMAP UID at or above this one has already been scanned by "
             "Fetch Mails, walking the mailbox newest-first. 0 = nothing "
             "scanned yet, so the next batch starts from the newest message. "
             "Lets a later press resume where it left off instead of "
             "re-scanning mail already checked.")

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
        """Manual 'Fetch Now' — same code path as the cron, errors surfaced."""
        self.fetch_mail(raise_exception=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Mailbox checked"),
                'message': _("Any new unread mail has been pulled into Mail Leads."),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    @api.model
    def _trigger_fetch_cron(self):
        """Wake the fetch cron so it runs now instead of at the next beat."""
        cron = self.env.ref(
            'crm_mail_lead_rk.ir_cron_crm_mail_lead_fetch', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    def _queue_full_import(self):
        """Arm 'Fetch Mails' on every server in ``self``: the cron will keep
        pulling read and unread mail from each mailbox, most recent first,
        until the whole folder has been imported."""
        self.sudo().write({'full_import_requested': True})

    def action_fetch_mails(self):
        """'Fetch Mails' button (CRM > Mail Leads list header).

        Arms a full import (every message not yet a Mail Lead — read and
        unread, any age, most recent first) on every confirmed CRM mailbox,
        imports a first small batch synchronously so the list refreshes with
        results at once, then wakes the cron to drain the rest automatically
        in the background. Every press (whether the background drain is still
        going or has caught up) adds whatever is still missing, so the total
        keeps climbing press after press until the whole mailbox is in Odoo —
        it never just repeats the same batch.
        """
        servers = self.filtered(lambda s: s.state == 'done')
        if not servers:
            raise UserError(_(
                "There is no confirmed CRM mail server yet. Add one under "
                "CRM > Configuration > Incoming Mail Servers (CRM), then press "
                "Test & Confirm."))
        servers._queue_full_import()
        imported, errors = servers.sudo()._run_fetch_mails()
        servers._trigger_fetch_cron()
        total = self.env['crm.mail.lead'].sudo().search_count(
            [('server_id', 'in', servers.ids)])
        still_running = bool(servers.sudo().filtered('full_import_requested'))
        if errors and not imported:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _("Fetch failed"),
                    'message': _(
                        "Could not fetch mail. Check Last Error on the CRM "
                        "mail server (CRM > Configuration > Incoming Mail "
                        "Servers (CRM))."),
                    'sticky': False,
                },
            }
        if still_running:
            message = _(
                "%(n)s imported just now, newest first — %(total)s mail "
                "lead(s) on file so far. Still more to bring in: it keeps "
                "importing automatically in the background, so the total "
                "keeps climbing on its own — press Fetch Mails again any "
                "time to check progress or add more right away.",
                n=imported, total=total)
        else:
            message = _(
                "%(n)s imported just now — %(total)s mail lead(s) on file. "
                "The whole mailbox is now caught up.", n=imported, total=total)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Fetch started") if still_running else _("Mailbox caught up"),
                'message': message,
                'next': {
                    'type': 'ir.actions.act_window',
                    'name': _("Mail Leads"),
                    'res_model': 'crm.mail.lead',
                    'view_mode': 'list,form',
                    'views': [(False, 'list'), (False, 'form')],
                    'target': 'main',
                    # Same default as the Mail Leads menu itself, so the
                    # refreshed list lands back on "To Assign" instead of
                    # showing every state.
                    'context': {'search_default_filter_new': 1},
                },
            },
        }

    def _run_fetch_mails(self):
        """Bounded synchronous fetch for the 'Fetch Mails' button.

        Imports up to ``FETCH_MAILS_SYNC_BATCH`` messages per server in the
        request itself, so the click gives immediate feedback; the cron
        (woken right after) drains the rest. Returns ``(imported, errors)``.
        """
        imported = errors = 0
        for server in self:
            try:
                res = server.fetch_mail(
                    raise_exception=False, commit=False, limit=FETCH_MAILS_SYNC_BATCH)
            except Exception:  # noqa: BLE001 - a button must not 500
                _logger.warning("CRM mail server %s: Fetch Mails failed.",
                                server.name, exc_info=True)
                errors += 1
                continue
            imported += res['imported']
            errors += res['errors']
        return imported, errors

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
        """Entry point of the every-5-minutes cron.

        While a server has a Fetch Mails full import in progress
        (``full_import_requested``), the progress API tells the runner to come
        straight back for the next batch instead of waiting for the next
        scheduled beat — so one button press drains the whole mailbox
        automatically, without the user pressing it again.
        """
        servers = self.search([('state', '=', 'done')])
        remaining = 0
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
                continue
            if server.full_import_requested:
                remaining += 1
        if remaining:
            self.env['ir.cron']._notify_progress(done=1, remaining=remaining)
        return True

    def fetch_mail(self, raise_exception=True, commit=False, limit=None):
        """Pull mail into ``crm.mail.lead`` for every server in ``self``.

        Two modes, chosen per server:

        * **Fetch Mails (full import)** — while ``full_import_requested`` is
          on, every message in the mailbox not already a Mail Lead is
          imported, read and unread, **most recent first**, resuming from
          ``full_import_floor_uid``. Once the mailbox is caught up the flag
          clears itself.
        * **Regular pass** — otherwise, only unread mail that arrived since
          the last run (unchanged from before).

        :param bool raise_exception: re-raise connection/parse failures instead
            of only logging them.
        :param bool commit: commit after each imported mail (cron usage only).
        :param int limit: cap on imports per server in *this* call, for the
            Fetch Mails button's synchronous first batch. ``None`` = up to
            ``FULL_IMPORT_BATCH`` (full import) or ``MAX_MESSAGES_PER_FETCH``
            (regular pass).
        :return: aggregated ``{'imported', 'skipped', 'failed', 'errors'}``
            across ``self``.
        """
        MailLead = self.env['crm.mail.lead'].sudo()
        totals = {'imported': 0, 'skipped': 0, 'failed': 0, 'errors': 0}
        for server in self:
            # Never fetch the same mailbox from two places at once (the
            # button's synchronous batch and the cron beat it just woke, or
            # two overlapping beats): the second writer to the crm.mail.server
            # row would otherwise hit a serialization error and Odoo would
            # retry the whole call, re-fetching everything.
            self.env.cr.execute(
                "SELECT pg_try_advisory_xact_lock(%s, %s)", (FETCH_LOCK_NS, server.id))
            if not self.env.cr.fetchone()[0]:
                _logger.info(
                    "CRM mail server %s: a fetch is already running, skipping.",
                    server.name)
                continue

            connection = None
            imported = skipped = failed = 0
            try:
                connection = server._connect()
                typ, _data = connection.select(server.folder or 'INBOX')
                if typ != 'OK':
                    raise UserError(_(
                        "Mailbox folder %(folder)s not found on %(server)s.",
                        folder=server.folder, server=server.server))

                if server.full_import_requested:
                    imported, skipped, failed = server._fetch_full_import(
                        connection, MailLead, limit or FULL_IMPORT_BATCH)
                else:
                    imported, skipped, failed = server._fetch_unread(
                        connection, MailLead, limit or MAX_MESSAGES_PER_FETCH, commit)

                server.sudo().write({
                    'last_fetch_date': fields.Datetime.now(),
                    'last_error': False,
                })
                _logger.info(
                    "CRM mail server %s: %d imported, %d skipped, %d failed (%s).",
                    server.name, imported, skipped, failed,
                    'full import' if server.full_import_requested else 'regular')
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

    def _fetch_unread(self, connection, MailLead, cap, commit):
        """Regular pass on the *selected* folder: unread mail that arrived
        since the last run. ``connection`` is logged in with the folder
        selected. Returns ``(imported, skipped, failed)``."""
        self.ensure_one()
        cutoff = self._get_fetch_cutoff()
        # IMAP SINCE has day granularity only and compares against the
        # server's own clock, so widen by a day here and apply the real
        # cut-off below against each mail's own Date header.
        typ, data = connection.search(
            None, 'UNSEEN', 'SINCE', self._imap_date(cutoff - timedelta(days=1)))
        if typ != 'OK':
            raise UserError(_("IMAP search failed on %s.", self.name))

        nums = data[0].split() if data and data[0] else []
        if len(nums) > cap:
            _logger.warning(
                "CRM mail server %s: %d unread messages matched, importing "
                "only the %d most recent this run; the rest follow on the "
                "next cron beats.", self.name, len(nums), cap)
            nums = nums[-cap:]

        imported = skipped = failed = 0
        for num in nums:
            # BODY.PEEK[] reads the message *without* setting \Seen, so an
            # unassigned mail stays unread in the user's inbox unless
            # 'Mark as Read in Mailbox' is on.
            typ, msg_data = connection.fetch(num, '(BODY.PEEK[])')
            raw = self._extract_raw_message(msg_data) if typ == 'OK' else None
            if not raw:
                failed += 1
                continue
            try:
                values = self._prepare_mail_lead_values(raw, cutoff)
            except Exception:  # noqa: BLE001 - one unparseable mail
                _logger.warning("CRM mail server %s: could not parse a message.",
                                self.name, exc_info=True)
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

            if self.mark_as_read:
                connection.store(num, '+FLAGS', '\\Seen')
            if commit:
                self.env.cr.commit()
        return imported, skipped, failed

    def _fetch_full_import(self, connection, MailLead, cap):
        """One batch of 'Fetch Mails': the most recent messages on the
        *selected* folder with an IMAP UID below ``full_import_floor_uid`` —
        read and unread, any age — up to ``cap`` this call, newest first.
        Resuming from the floor instead of re-scanning the whole mailbox every
        beat is what keeps each beat fast; fetching several message bodies per
        IMAP round-trip (``BODY_FETCH_CHUNK``) is what keeps it fast enough to
        finish inside the cron interval even on a slow connection.

        ``connection`` is logged in with the folder selected.
        Returns ``(imported, skipped, failed)``.
        """
        self.ensure_one()
        floor = self.full_import_floor_uid
        # floor=0 means nothing scanned yet: search the whole folder and start
        # from its newest message. Otherwise only what's still below the floor
        # is unscanned.
        search_range = '1:%d' % (floor - 1) if floor else '1:*'
        typ, data = connection.uid('SEARCH', 'UID', search_range)
        if typ != 'OK':
            raise UserError(_("IMAP UID search failed on %s.", self.name))
        uids = sorted(
            (uid for uid in (int(x) for x in (data[0] or b'').split())
             if not floor or uid < floor),
            reverse=True)  # newest first
        if not uids:
            self.sudo().write({'full_import_requested': False})
            return 0, 0, 0

        batch = uids[:cap]
        imported = skipped = failed = 0
        for start in range(0, len(batch), BODY_FETCH_CHUNK):
            chunk = batch[start:start + BODY_FETCH_CHUNK]
            typ, msg_data = connection.uid(
                'FETCH', ','.join(str(uid) for uid in chunk), '(UID BODY.PEEK[])')
            raw_by_uid = self._extract_raw_messages(msg_data) if typ == 'OK' else {}
            for uid in chunk:
                raw = raw_by_uid.get(uid)
                if not raw:
                    failed += 1
                else:
                    try:
                        with self.env.cr.savepoint():
                            values = self._prepare_mail_lead_values(raw, cutoff=None)
                            if not values:
                                skipped += 1
                            else:
                                attachments = values.pop('__attachments__', [])
                                mail_lead = MailLead.create(values)
                                if attachments:
                                    mail_lead._store_attachments(attachments)
                                imported += 1
                    except Exception:  # noqa: BLE001 - one unparseable / un-storable mail
                        _logger.warning("CRM mail server %s: could not import UID %s.",
                                        self.name, uid, exc_info=True)
                        failed += 1
                if self.mark_as_read:
                    try:
                        connection.uid('STORE', str(uid), '+FLAGS', '(\\Seen)')
                    except Exception:  # noqa: BLE001
                        pass

        write_vals = {'full_import_floor_uid': min(batch)}
        if len(uids) <= cap:
            # Caught up with everything that was in the mailbox as of the
            # search above — stand down until the next Fetch Mails press.
            write_vals['full_import_requested'] = False
        self.sudo().write(write_vals)
        return imported, skipped, failed

    @staticmethod
    def _extract_raw_message(msg_data):
        """Pull the raw RFC-2822 bytes out of a single-message FETCH response."""
        return next(
            (part[1] for part in (msg_data or [])
             if isinstance(part, tuple) and len(part) > 1),
            None)

    @staticmethod
    def _extract_raw_messages(msg_data):
        """Pull ``{uid: raw_bytes}`` out of a multi-UID FETCH response —
        Gmail (and IMAP servers generally) include ``UID nnnn`` in each
        message's response descriptor for a ``UID FETCH``, which is what lets
        several messages fetched in one round-trip be told apart."""
        result = {}
        for part in (msg_data or []):
            if not isinstance(part, tuple) or len(part) < 2:
                continue
            match = re.search(rb'UID (\d+)', part[0] or b'')
            if match:
                result[int(match.group(1))] = part[1]
        return result

    def _prepare_mail_lead_values(self, raw_message, cutoff=None):
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
        # only narrow this down to the day. Skipped for a full import
        # (cutoff=None): every message not already a Mail Lead counts,
        # whatever its age.
        if cutoff is not None and date_received < cutoff:
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
