from datetime import timedelta

from odoo import models, fields, api, _

# Days a customer invoice may sit in draft (unapproved) from its creation
# before it is archived out of the active invoice list.
STALE_DRAFT_GRACE_DAYS = 7

# How far ahead of that cut-off the creator is warned.
STALE_DRAFT_WARN_LEAD_DAYS = 2

# Marker on the reminder activity's summary. The archive pass clears only the
# activities it raised itself, so unrelated To-Do activities sitting on the
# same invoice are left alone.
STALE_DRAFT_ACTIVITY_MARKER = "Stale draft invoice"

# Only customer-side documents are policed. Vendor bills routinely sit in
# draft while supporting documents are chased, and archiving those would hide
# real liabilities.
STALE_DRAFT_MOVE_TYPES = ('out_invoice', 'out_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    # account.move has no `active` field in stock Odoo 18, so this adds one.
    # Consequence to keep in mind: every ORM search on account.move now
    # implicitly filters active = True unless it passes active_test=False.
    # Only stale *drafts* are ever archived, and draft moves are already out of
    # scope for the accounting reports (which read posted entries), so the
    # blast radius is the invoice list views.
    active = fields.Boolean(
        string='Active',
        default=True,
        # Duplicating an archived draft should hand back a usable one.
        copy=False,
        help="Unticked when the auto-archive cron retires a draft invoice that "
             "was never approved. Untick/retick manually to archive or restore "
             "an invoice by hand.",
    )

    stale_draft_deadline = fields.Date(
        string='Draft Approval Deadline',
        compute='_compute_stale_draft_deadline',
        store=True,
        help="Date by which this draft invoice must be posted (approved) or it "
             "is archived automatically: %s days after it was created. Empty "
             "once the invoice leaves draft." % STALE_DRAFT_GRACE_DAYS,
    )

    stale_draft_warned_date = fields.Date(
        string='Archive Warning Sent',
        readonly=True,
        copy=False,
        help="Date the creator was warned that this draft is about to be "
             "archived. An invoice is never archived without a warning having "
             "gone out on an earlier day.",
    )

    stale_draft_archived_date = fields.Date(
        string='Auto-Archived On',
        readonly=True,
        copy=False,
        help="Date the auto-archive cron retired this draft. Once set, the "
             "invoice is never auto-archived again — so restoring it from the "
             "archive is permanent unless someone archives it by hand.",
    )

    stale_draft_days_left = fields.Integer(
        string='Days Left To Approve',
        compute='_compute_stale_draft_warning',
        help="Days remaining before this draft invoice is auto-archived. "
             "Negative once the deadline has passed.",
    )

    stale_draft_warning = fields.Char(
        string='Stale Draft Warning',
        compute='_compute_stale_draft_warning',
        help="Live text for the draft-expiry banner. Recomputed on every form "
             "load, so it is correct even before the daily cron has run.",
    )

    @api.depends('create_date', 'state', 'move_type')
    def _compute_stale_draft_deadline(self):
        for move in self:
            if (
                move.state == 'draft'
                and move.move_type in STALE_DRAFT_MOVE_TYPES
                and move.create_date
            ):
                created = fields.Date.to_date(move.create_date)
                move.stale_draft_deadline = created + timedelta(days=STALE_DRAFT_GRACE_DAYS)
            else:
                move.stale_draft_deadline = False

    @api.depends('stale_draft_deadline', 'stale_draft_archived_date', 'active')
    def _compute_stale_draft_warning(self):
        today = fields.Date.context_today(self)
        for move in self:
            if not move.stale_draft_deadline:
                move.stale_draft_days_left = 0
                move.stale_draft_warning = False
                continue

            days_left = (move.stale_draft_deadline - today).days
            move.stale_draft_days_left = days_left

            if not move.active:
                move.stale_draft_warning = (
                    "This draft invoice was archived automatically because it "
                    "was not approved within %s days of creation. Restore it "
                    "from the Action menu to work on it again."
                    % STALE_DRAFT_GRACE_DAYS
                )
            elif days_left > STALE_DRAFT_WARN_LEAD_DAYS:
                move.stale_draft_warning = False
            elif days_left > 0:
                move.stale_draft_warning = (
                    "This invoice is still in draft and will be archived "
                    "automatically in %s day(s), on %s, unless it is confirmed."
                    % (days_left, move.stale_draft_deadline)
                )
            else:
                move.stale_draft_warning = (
                    "This invoice has been in draft for more than %s days and "
                    "is due to be archived automatically. Confirm it now to "
                    "keep it." % STALE_DRAFT_GRACE_DAYS
                )

    # ------------------------------------------------------------------
    # Auto-archive of unapproved drafts
    # ------------------------------------------------------------------

    def _stale_draft_notify_creator(self):
        """Warn each invoice's creator that it is about to be archived.

        Posts to the chatter addressed to the creator (an Odoo inbox
        notification, plus an email if outgoing mail is working) and raises a
        To-Do activity on them dated for the archive deadline.
        """
        for move in self:
            creator = move.create_uid
            deadline = move.stale_draft_deadline

            if creator and creator.active and not creator.share:
                move.message_post(
                    body=_(
                        "<p>This draft invoice has not been approved and is "
                        "scheduled to be <b>archived automatically on %(deadline)s</b>, "
                        "%(grace)s days after it was created.</p>"
                        "<p>Confirm the invoice before then to keep it in the "
                        "active list.</p>",
                        deadline=deadline,
                        grace=STALE_DRAFT_GRACE_DAYS,
                    ),
                    partner_ids=creator.partner_id.ids,
                    subtype_xmlid='mail.mt_comment',
                )
                move.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=deadline,
                    summary="%s — approve or it is archived on %s" % (
                        STALE_DRAFT_ACTIVITY_MARKER, deadline,
                    ),
                    note=_(
                        "Draft invoice %(name)s for %(partner)s has been "
                        "unapproved since %(created)s. It will be archived "
                        "automatically on %(deadline)s.",
                        name=move.display_name,
                        partner=move.partner_id.display_name or _("no customer"),
                        created=fields.Date.to_date(move.create_date),
                        deadline=deadline,
                    ),
                    user_id=creator.id,
                )
            else:
                # No usable creator to address (archived user, or a record
                # created by a portal/system user). Still stamp the warning so
                # the invoice is not stuck un-archivable forever.
                move.message_post(
                    body=_(
                        "This draft invoice is scheduled to be archived "
                        "automatically on %(deadline)s. Its creator could not "
                        "be notified.",
                        deadline=deadline,
                    )
                )

        self.write({'stale_draft_warned_date': fields.Date.context_today(self)})

    def _stale_draft_clear_activities(self):
        """Drop the reminder activities this feature raised, and only those."""
        activity_type = self.env.ref(
            'mail.mail_activity_data_todo', raise_if_not_found=False,
        )
        if not activity_type or not self:
            return
        self.env['mail.activity'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', 'in', self.ids),
            ('activity_type_id', '=', activity_type.id),
            ('summary', 'like', STALE_DRAFT_ACTIVITY_MARKER),
        ]).unlink()

    def _stale_draft_archive(self):
        """Archive the drafts in self and tell their creators it happened."""
        for move in self:
            creator = move.create_uid
            partner_ids = (
                creator.partner_id.ids
                if creator and creator.active and not creator.share
                else []
            )
            move.message_post(
                body=_(
                    "<p>Archived automatically: this invoice was still in draft "
                    "%(grace)s days after it was created and was never "
                    "approved.</p>"
                    "<p>Use <b>Action → Unarchive</b> to bring it back. It "
                    "will not be auto-archived a second time.</p>",
                    grace=STALE_DRAFT_GRACE_DAYS,
                ),
                partner_ids=partner_ids,
                subtype_xmlid='mail.mt_comment',
            )

        self._stale_draft_clear_activities()
        self.write({
            'active': False,
            'stale_draft_archived_date': fields.Date.context_today(self),
        })

    @api.model
    def _cron_archive_stale_draft_invoices(self):
        """Warn on, then archive, customer invoices left unapproved in draft.

        Two passes, deliberately on different days for any given invoice: the
        archive pass only touches invoices whose warning went out on an
        *earlier* day. If the cron has been down and an invoice sails past its
        deadline unwarned, it gets warned on this run and archived on the next
        one — so the creator always gets notice first.
        """
        today = fields.Date.context_today(self)

        base_domain = [
            ('move_type', 'in', STALE_DRAFT_MOVE_TYPES),
            ('state', '=', 'draft'),
            ('stale_draft_deadline', '!=', False),
            # Archived once, never chased again — restoring an invoice from the
            # archive is the escape hatch from this policy.
            ('stale_draft_archived_date', '=', False),
        ]

        to_warn = self.search(base_domain + [
            ('stale_draft_warned_date', '=', False),
            ('stale_draft_deadline', '<=', today + timedelta(days=STALE_DRAFT_WARN_LEAD_DAYS)),
        ])
        if to_warn:
            to_warn._stale_draft_notify_creator()

        # A NULL stale_draft_warned_date never satisfies '<', so an unwarned
        # invoice can't be picked up here — including the ones just warned above.
        to_archive = self.search(base_domain + [
            ('stale_draft_deadline', '<=', today),
            ('stale_draft_warned_date', '<', today),
        ])
        if to_archive:
            to_archive._stale_draft_archive()

        return True

    def action_post(self):
        # Approving an invoice ends the countdown: clear the reminder activity
        # so it stops sitting in the creator's To-Do list.
        res = super().action_post()
        self._stale_draft_clear_activities()
        return res
