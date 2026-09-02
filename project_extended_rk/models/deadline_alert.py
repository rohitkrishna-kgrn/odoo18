"""Proactive deadline alerts for projects and tasks.

Two notifications go out per deadline, to the Project Manager and the head of
the project's department:

  * an advance alert once the deadline comes within DEADLINE_ALERT_LEAD_DAYS
    days, and
  * a second alert on the deadline date itself, if the record is still open.

Both are posted to the record's chatter addressed to the recipients, which
gives an Odoo inbox notification plus an outgoing email — the same mechanism
the rest of the custom modules notify with.

Nothing is sent for a deadline that has already passed: the advance and
due-date alerts are the whole feature, and overdue tracking is a separate
concern (see project_overdue_extended_rk).
"""

import logging
from datetime import timedelta

from markupsafe import Markup

from odoo.tools.mail import generate_tracking_message_id

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# How far ahead of the deadline the advance warning goes out.
DEADLINE_ALERT_LEAD_DAYS = 7

# Marker in the activity summary, so the reminders raised here can be told
# apart from every other To-Do sitting on the record.
DEADLINE_ALERT_ACTIVITY_MARKER = "Deadline reminder"


class DeadlineAlertMixin(models.AbstractModel):
    """Shared deadline-alert bookkeeping.

    A concrete model must set ``_deadline_alert_field`` to the name of its
    deadline field and implement ``_deadline_alert_is_open``,
    ``_deadline_alert_manager`` and ``_deadline_alert_department``.
    """

    _name = 'deadline.alert.mixin'
    _description = 'Proactive Deadline Alerts'

    # Name of the Date / Datetime field carrying the deadline.
    _deadline_alert_field = None

    deadline_alert_advance_sent_for = fields.Date(
        string='Advance Alert Sent For',
        copy=False,
        readonly=True,
        help="Deadline the advance alert was sent for. It stores the deadline "
             "itself rather than a flag, so moving the deadline re-arms the "
             "alert automatically and a re-run on the same day sends nothing.",
    )

    deadline_alert_due_sent_for = fields.Date(
        string='Due-Date Alert Sent For',
        copy=False,
        readonly=True,
        help="Deadline the due-date alert was sent for. Same re-arming "
             "behaviour as the advance alert.",
    )

    # ------------------------------------------------------------------
    # Hooks the concrete models fill in
    # ------------------------------------------------------------------

    def _deadline_alert_date(self):
        """The deadline as a plain date, or False when it is not set."""
        self.ensure_one()
        value = self[self._deadline_alert_field]
        # The carrier is a Date on project.project and a Datetime on
        # project.task; truncate in UTC, the same way the overdue category on
        # these records is derived, so the alert and the overdue ribbon never
        # disagree about which day a deadline falls on.
        return fields.Date.to_date(value) if value else False

    def _deadline_alert_is_open(self):
        """Whether the record still needs doing (and so deserves an alert)."""
        raise NotImplementedError

    def _deadline_alert_manager(self):
        """The Project Manager to alert, as a res.users recordset."""
        raise NotImplementedError

    def _deadline_alert_department(self):
        """The hr.department whose head should be alerted."""
        raise NotImplementedError

    def _deadline_alert_label(self):
        """Human-readable name for this kind of record."""
        return _("Record")

    # ------------------------------------------------------------------
    # Recipients
    # ------------------------------------------------------------------

    def _deadline_alert_recipients(self):
        """Project Manager plus the head of the project's department.

        Falls back to the *Deadline Alert Watcher* checkbox group when neither
        can be resolved — a project with no manager, or a department with no
        manager set — so an alert is never silently dropped. Ticking that box
        on a user form is the only thing needed to add a catch-all recipient.
        """
        self.ensure_one()
        users = self._deadline_alert_manager() | self._deadline_alert_department().manager_id.user_id
        # Never address archived accounts or portal/public users.
        users = users.filtered(lambda u: u.active and not u.share)
        if users:
            return users

        watchers = self.env.ref(
            'project_extended_rk.group_deadline_alert_watcher',
            raise_if_not_found=False,
        )
        if not watchers:
            return self.env['res.users']
        return watchers.users.filtered(lambda u: u.active and not u.share)

    # ------------------------------------------------------------------
    # Message body
    # ------------------------------------------------------------------

    def _deadline_alert_details_table(self, deadline):
        self.ensure_one()
        manager = self._deadline_alert_manager()
        department = self._deadline_alert_department()
        head = department.manager_id
        rows = [
            (_("Deadline"), fields.Date.to_string(deadline)),
            (_("Project Manager"), manager.name or _("not set")),
            (_("Department"), department.display_name or _("not set")),
            (_("Department Head"), head.name or _("not set")),
            (_("Stage"), self.stage_id.display_name or _("not set")),
        ]
        body = Markup("")
        for label, value in rows:
            body += Markup("<tr><th style='text-align:left'>%s</th><td>%s</td></tr>") % (label, value)
        return Markup("<table class='table table-sm'><tbody>%s</tbody></table>") % body

    def _deadline_alert_body(self, kind, deadline):
        self.ensure_one()
        label = self._deadline_alert_label()
        if kind == 'advance':
            days_left = (deadline - fields.Date.context_today(self)).days
            headline = _("Deadline in %(days)s day(s): %(name)s",
                         days=days_left, name=self.display_name)
            lead = _("This %(label)s is due on %(deadline)s and is still open.",
                     label=label.lower(), deadline=fields.Date.to_string(deadline))
        else:
            headline = _("Deadline is today: %(name)s", name=self.display_name)
            lead = _("This %(label)s is due today and is still open.",
                     label=label.lower())
        closing = _("Please complete it, or record a revised delivery date and "
                    "the reason for the delay.")
        return Markup("<p><b>%s</b></p><p>%s</p>%s<p>%s</p>") % (
            headline, lead, self._deadline_alert_details_table(deadline), closing,
        )

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _deadline_alert_schedule_activity(self, deadline):
        """Raise a To-Do on the Project Manager, dated the deadline.

        This is what survives the mail server being down — the PM sees it on
        their Odoo dashboard whether or not the email is delivered.
        """
        self.ensure_one()
        # Same filter the recipients use: an archived or portal account cannot
        # act on a To-Do, so raising one on them just leaves litter behind.
        manager = self._deadline_alert_manager().filtered(
            lambda u: u.active and not u.share
        )[:1]
        if not manager:
            return

        # Drop any earlier reminder this feature raised (and only those), so a
        # deadline that has been moved does not leave a stale To-Do behind.
        self._deadline_alert_clear_activities()

        self.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=deadline,
            summary="%s — due %s" % (
                DEADLINE_ALERT_ACTIVITY_MARKER, fields.Date.to_string(deadline),
            ),
            note=_("%(label)s %(name)s is due on %(deadline)s.",
                   label=self._deadline_alert_label(),
                   name=self.display_name,
                   deadline=fields.Date.to_string(deadline)),
            user_id=manager.id,
        )

    def _deadline_alert_clear_activities(self):
        """Remove the To-Dos this feature raised on these records."""
        if not self:
            return
        self.env['mail.activity'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', 'in', self.ids),
            ('summary', 'like', DEADLINE_ALERT_ACTIVITY_MARKER),
        ]).unlink()

    def _deadline_alert_notify(self, kind):
        """Post the alert for every record in self and stamp it as sent."""
        stamp_field = (
            'deadline_alert_advance_sent_for' if kind == 'advance'
            else 'deadline_alert_due_sent_for'
        )
        for record in self:
            deadline = record._deadline_alert_date()
            recipients = record._deadline_alert_recipients()
            body = record._deadline_alert_body(kind, deadline)

            if recipients:
                record.message_post(
                    body=body,
                    partner_ids=recipients.mapped('partner_id').ids,
                    subtype_xmlid='mail.mt_comment',
                )
            else:
                # Still leave the trail on the record, and still stamp it, so
                # an unassigned record does not re-notify nobody every day.
                record.message_post(body=body + (Markup("<p><i>%s</i></p>") % _(
                    "No Project Manager, department head or Deadline Alert "
                    "Watcher could be identified to notify.")))

            if kind == 'advance':
                record._deadline_alert_schedule_activity(deadline)

            record.write({stamp_field: deadline})

    # ------------------------------------------------------------------
    # Test send
    # ------------------------------------------------------------------

    def _deadline_alert_test_body(self, kind, deadline):
        """The real alert body, behind an unmistakable test banner.

        The banner matters: these go to the same people the live alert goes
        to, and a deadline warning that turns out to be a drill is worse than
        no warning at all.
        """
        self.ensure_one()
        banner = Markup(
            "<div style='border-left:4px solid #d9822b;background:#fdf6ec;"
            "padding:8px 12px;margin-bottom:12px'>"
            "<b>%s</b><br/><span style='font-size:12px'>%s</span></div>"
        ) % (
            _("TEST MESSAGE — no action required"),
            _("Sent manually to check the deadline alert format and delivery. "
              "The scheduled alerts are unaffected and this record has not "
              "been marked as alerted."),
        )
        return banner + self._deadline_alert_body(kind, deadline)

    def _deadline_alert_test_subject(self, kind, deadline):
        self.ensure_one()
        if kind == 'advance':
            days_left = (deadline - fields.Date.context_today(self)).days
            return _("[TEST] Deadline in %(days)s day(s): %(name)s",
                     days=days_left, name=self.display_name)
        return _("[TEST] Deadline is today: %(name)s", name=self.display_name)

    def _deadline_alert_deliver_inbox_copy(self, recipients, subject, body):
        """Put a copy straight into the recipients' Odoo inbox.

        A test that cannot be seen is not a test. Recipients whose Odoo
        preference is "by email" get nothing they can read while the outgoing
        mail server is refusing to send — and Odoo hides ``user_notification``
        messages from the chatter, so the record shows nothing either.

        This is a deliberate second message rather than a second notification
        on the first one: ``mail_notification`` carries a unique index on
        (message, partner), so a partner can be reached by email or by inbox
        for a given message, never both.
        """
        self.ensure_one()
        author_id, email_from = self._message_compute_author(raise_on_email=True)
        message = self.env['mail.message'].sudo().create({
            'model': self._name,
            'res_id': self.id,
            'message_type': 'user_notification',
            'subtype_id': self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
            'subject': subject,
            'body': body,
            'author_id': author_id,
            'email_from': email_from,
            'is_internal': True,
            # mail.message._get_reply_to() cannot resolve a 'user_notification'
            # that carries a res_id — it looks the value up on an empty
            # recordset and raises KeyError. Setting it here is what core's
            # own message_notify() does for exactly this reason.
            'reply_to': self._notify_get_reply_to(default=email_from)[self.id],
            'message_id': generate_tracking_message_id('deadline-alert-test'),
        })
        self._notify_thread_by_inbox(
            message,
            [{'id': u.partner_id.id, 'uid': u.id, 'notif': 'inbox'}
             for u in recipients],
        )
        return message

    def _deadline_alert_send_test(self, recipients, kind='advance',
                                  deadline=None, inbox_copy=False):
        """Send the alert as a real email and report what the server did.

        This deliberately builds a plain ``mail.mail`` addressed to each
        recipient's own address rather than going through ``message_notify``.
        A notification would be routed by each recipient's Odoo preference and
        would land in the queue with an empty *To*, which is awkward to check;
        an explicit ``email_to`` shows up in Settings > Technical > Email >
        Emails as an ordinary outgoing message, which is where a mail test is
        actually read.

        The mails are kept (``auto_delete=False``) and carry no ``model`` /
        ``res_id``, so they stay inspectable in the queue and do not add a
        stray entry to the record's chatter. A message that fails stays in the
        queue and can be retried from that same screen once the outgoing mail
        server works again.

        Deliberately side-effect free with respect to the live feature: the
        ``..._sent_for`` stamps are left alone and no To-Do is raised, so a
        test send never suppresses or duplicates a real alert.

        Returns a list of ``(email, state, reason)``.
        """
        self.ensure_one()
        deadline = deadline or self._deadline_alert_date()
        if not deadline:
            raise UserError(_(
                "%(name)s has no deadline set, so there is nothing to alert "
                "about. Pick a date under Simulate Deadline.",
                name=self.display_name,
            ))

        recipients = recipients.filtered(lambda u: u.active and not u.share)
        addressed = recipients.filtered(lambda u: u.email)
        if not addressed:
            raise UserError(_(
                "None of the selected recipients has an email address set, so "
                "there is nowhere to send the test."
            ))

        subject = self._deadline_alert_test_subject(kind, deadline)
        body = self._deadline_alert_test_body(kind, deadline)

        if inbox_copy:
            self._deadline_alert_deliver_inbox_copy(recipients, subject, body)

        results = []
        Mail = self.env['mail.mail'].sudo()
        for user in addressed:
            mail = Mail.create({
                'subject': subject,
                'body_html': body,
                'email_to': user.email,
                'email_from': self._deadline_alert_test_email_from(),
                'auto_delete': False,
            })
            # raise_exception=False: a refusing mail server must not abort the
            # wizard — reporting what it said is the entire point.
            mail.send(raise_exception=False)
            mail.invalidate_recordset(['state', 'failure_reason'])
            reason = (mail.failure_reason or '').replace('\n', ' ').strip()
            results.append((user.email, mail.state, reason))
            _logger.info(
                "Deadline alert TEST (%s) for %s#%s to %s: mail.mail #%s %s %s",
                kind, self._name, self.id, user.email, mail.id, mail.state,
                reason[:200],
            )
        return results

    def _deadline_alert_test_email_from(self):
        """Sender address: whatever the live alerts would already use."""
        server = self.env['ir.mail_server'].sudo().search([], limit=1)
        return (
            server.smtp_user
            or self.env.company.email
            or self.env.user.email_formatted
        )

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------

    @api.model
    def _cron_deadline_alerts(self):
        """Send whichever deadline alerts are owed today.

        One window query covers both alerts — everything due between today and
        today + lead days — and each record is then sorted into the advance or
        the due-date bucket. Records already stamped for that exact deadline
        are skipped, so re-running on the same day sends nothing.

        A deadline set *inside* the lead window (a task created three days
        before it is due) still gets its advance alert on the next run rather
        than being skipped for never having been exactly seven days out.
        """
        today = fields.Date.context_today(self)
        window_end = today + timedelta(days=DEADLINE_ALERT_LEAD_DAYS)
        deadline_field = self._deadline_alert_field

        candidates = self.search([
            (deadline_field, '>=', "%s 00:00:00" % today),
            (deadline_field, '<=', "%s 23:59:59" % window_end),
        ])

        advance = self.browse()
        due = self.browse()
        for record in candidates:
            if not record._deadline_alert_is_open():
                continue
            deadline = record._deadline_alert_date()
            if not deadline:
                continue
            if deadline == today:
                if record.deadline_alert_due_sent_for != deadline:
                    due |= record
            elif today < deadline <= window_end:
                if record.deadline_alert_advance_sent_for != deadline:
                    advance |= record

        if advance:
            advance._deadline_alert_notify('advance')
        if due:
            due._deadline_alert_notify('due')

        _logger.info(
            "Deadline alerts on %s: %s scanned, %s advance, %s due today.",
            self._name, len(candidates), len(advance), len(due),
        )


class ProjectProject(models.Model):
    _name = 'project.project'
    _inherit = ['project.project', 'deadline.alert.mixin']

    # project.project has no deadline of its own: the core planned end date
    # ('date', shown as Deadline) is the firm's project deadline — it is what
    # the SO line's engagement end writes to and what the MIS report reads.
    _deadline_alert_field = 'date'

    def _deadline_alert_is_open(self):
        self.ensure_one()
        return self.active and not (self.stage_id and self.stage_id.fold)

    def _deadline_alert_manager(self):
        self.ensure_one()
        return self.user_id

    def _deadline_alert_department(self):
        self.ensure_one()
        return self.department_id

    def _deadline_alert_label(self):
        return _("Project")


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'deadline.alert.mixin']

    _deadline_alert_field = 'date_deadline'

    def _deadline_alert_is_open(self):
        self.ensure_one()
        if not self.active:
            return False
        # Three independent "this is finished" signals live on tasks here and
        # they do not always agree, so any one of them closes the task off:
        # the core state, the custom state_additional, and a folded stage.
        if self.state in ('1_done', '1_canceled'):
            return False
        if self.state_additional in ('completed', 'cancelled'):
            return False
        return not (self.stage_id and self.stage_id.fold)

    def _deadline_alert_manager(self):
        self.ensure_one()
        # A task carries assignees; the Project Manager is on its project.
        return self.project_id.user_id

    def _deadline_alert_department(self):
        self.ensure_one()
        return self.project_id.department_id

    def _deadline_alert_label(self):
        return _("Task")
