from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

from .account_followup_log import FOLLOWUP_METHODS

LATE_PAYMENT_PENALTY_TEXT = (
    "Late payment penalty: AED 50 per day will be charged on all overdue "
    "invoices from the due date until settlement."
)

# Days past due beyond which an invoice can no longer be settled or closed
# until the AR Responsible has confirmed ownership and at least one follow-up
# has been logged.
AR_CLOSE_LOCK_DAYS = 180

# Days past due beyond which an outstanding invoice with nothing in its
# Follow-up Log is flagged automatically.
AR_NO_FOLLOWUP_FLAG_DAYS = 30


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Locked footer clause: not editable per-invoice, always recomputed for
    # customer invoices/credit notes so it can't be removed or altered.
    narration = fields.Html(readonly=True)

    ar_responsible_id = fields.Many2one(
        'res.users',
        string='AR Responsible',
        domain=[('share', '=', False)],
        tracking=True,
        help="User responsible for following up on collection of this invoice.",
    )

    # No longer a field anyone fills in: the Sale Order Line is the single
    # engagement link on every document now, and this just carries the project
    # that line delivers so the PM / Team related fields, the MIS views and the
    # weekly overdue report keep resolving. Readonly rather than removed --
    # retainership invoices and vendor debit notes have no sale order line and
    # still need a project stamped on them programmatically.
    service_engagement_id = fields.Many2one(
        'project.project',
        string='Service Engagement',
        tracking=True,
        readonly=True,
        help="Project the Sale Order Line on this invoice delivers. Derived "
             "from the Sale Order Line; not picked by hand.",
    )

    # Read off the document itself rather than picked from a dropdown: a
    # reversal is a credit note, an invoice raised from a retainership contract
    # is a retainer, one flagged as an advance is an advance, and everything
    # else is a completion invoice.
    invoice_type_classification = fields.Selection(
        [
            ('advance', 'Advance'),
            ('completion', 'Completion'),
            ('retainer', 'Retainer'),
            ('credit_note', 'Credit Note'),
        ],
        string='Invoice Type',
        compute='_compute_invoice_type_classification',
        store=True,
        tracking=True,
        copy=False,
        help="Advance, Retainer and Credit Note are recognised from the "
             "document itself and cannot be changed. Anything else is left "
             "blank for the person raising the invoice to classify.",
    )

    # The field the user actually edits. Keeping the manual choice in its own
    # column, rather than making the derived field writable, is what stops a
    # stray write turning an Advance into something it is not: the derived
    # field is a plain stored compute and simply cannot be written. The form
    # shows exactly one of the two at a time, under the same label, so it reads
    # as a single field.
    # Completion is the judgement this dropdown exists to capture: "yes, this
    # is the invoice that closes the engagement" -- or blank, meaning not yet.
    # Advance is here only so the advance invoice raised when a sale order is
    # approved can stamp itself; those documents also carry advance_invoice, so
    # they classify automatically and the locked field is what the form shows.
    # Retainer and Credit Note are read off the document and never set by hand.
    invoice_type_manual = fields.Selection(
        [
            ('advance', 'Advance'),
            ('completion', 'Completion'),
        ],
        string='Invoice Type',
        copy=False,
        tracking=True,
        help="Mark the invoice that closes the engagement as a Completion. "
             "Advance is stamped automatically on the advance invoice raised "
             "from an approved sale order. Retainer and Credit Note are "
             "recognised from the document itself and cannot be set by hand.",
    )

    invoice_type_is_automatic = fields.Boolean(
        string='Invoice Type Is Automatic',
        compute='_compute_invoice_type_is_automatic',
        help="True when the document classifies itself, so the dropdown is "
             "locked.",
    )

    # Materialised from the chatter, never typed into directly: every Log
    # note and every completed activity on a customer invoice creates a row
    # (see _followup_log_from_message). readonly so no view, import or Studio
    # tweak can put a follow-up here that has no chatter message behind it.
    followup_log_ids = fields.One2many(
        'account.invoice.followup.log',
        'move_id',
        string='Follow-up Log',
        readonly=True,
    )

    last_followup_date = fields.Date(
        string='Last Follow-up Date',
        compute='_compute_last_followup',
        store=True,
    )
    last_followup_method = fields.Selection(
        FOLLOWUP_METHODS,
        string='Last Follow-up Method',
        compute='_compute_last_followup',
        store=True,
    )
    last_followup_response = fields.Text(
        string='Last Client Response',
        compute='_compute_last_followup',
        store=True,
    )

    followup_log_status = fields.Selection(
        [('present', 'Present'), ('missing', 'Missing')],
        string='Follow-up Log Status',
        compute='_compute_followup_log_status',
        store=True,
    )

    followup_count = fields.Integer(
        string='Follow-ups',
        compute='_compute_followup_log_status',
        store=True,
        help="How many follow-ups have been logged against this invoice.",
    )

    # The whole log flattened into one cell, so an AR export carries the chase
    # history and not just its last line. Not stored: it is a presentation of
    # followup_log_ids, read on demand by the export and by the weekly report.
    followup_history = fields.Text(
        string='Follow-up History',
        compute='_compute_followup_history',
        help="Every follow-up logged on this invoice, oldest first, as "
             "date | method | logged by | client response.",
    )

    engagement_team_id = fields.Many2one(
        'hr.department',
        string='Team',
        related='service_engagement_id.department_id',
        store=True,
    )

    engagement_pm_id = fields.Many2one(
        'res.users',
        string='PM',
        related='service_engagement_id.user_id',
        store=True,
    )

    invoice_age_days = fields.Integer(
        string='Invoice Age (Days)',
        compute='_compute_ar_aging',
        store=True,
        help="Days past the due date. 0 while not yet due or once settled.",
    )

    aging_bucket = fields.Selection(
        [
            ('not_due', 'Not Due'),
            ('0_30', '0-30 Days'),
            ('31_60', '31-60 Days'),
            ('61_90', '61-90 Days'),
            ('90_plus', '90+ Days'),
        ],
        string='Aging Bucket',
        compute='_compute_ar_aging',
        store=True,
    )

    credit_hold = fields.Boolean(
        string='Credit Hold',
        compute='_compute_credit_hold',
        store=True,
        help="Client's outstanding receivable balance exceeds their credit limit.",
    )

    def _compute_narration(self):
        super()._compute_narration()
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund'):
                move.narration = LATE_PAYMENT_PENALTY_TEXT

    @api.depends('followup_log_ids.date', 'followup_log_ids.method', 'followup_log_ids.response')
    def _compute_last_followup(self):
        for move in self:
            last = move.followup_log_ids[:1]
            move.last_followup_date = last.date
            move.last_followup_method = last.method
            move.last_followup_response = last.response

    @api.depends('followup_log_ids')
    def _compute_followup_log_status(self):
        for move in self:
            move.followup_count = len(move.followup_log_ids)
            move.followup_log_status = 'present' if move.followup_log_ids else 'missing'

    @api.depends('followup_log_ids.date', 'followup_log_ids.method',
                 'followup_log_ids.response', 'followup_log_ids.user_id')
    def _compute_followup_history(self):
        for move in self:
            move.followup_history = move._followup_history_text()

    # ------------------------------------------------------------------
    # Chatter -> Follow-up Log
    # ------------------------------------------------------------------
    # The Follow-up Log is not typed into any more. AR chases the client the
    # way they already work -- a Log note in the chatter, or a scheduled
    # activity marked done -- and each of those materialises one follow-up row
    # here, which is what the AR aging dashboard, the outstanding partner
    # ledger, the weekly overdue report and the 180-day close lock all read.

    def message_post(self, **kwargs):
        message = super().message_post(**kwargs)
        if message and self.move_type in ('out_invoice', 'out_refund'):
            self._followup_log_from_message(message)
        return message

    def _followup_log_from_message(self, message):
        """Materialise a follow-up row for a qualifying chatter message."""
        self.ensure_one()
        Log = self.env['account.invoice.followup.log']
        vals = Log._prepare_from_message(
            self, message,
            feedback=self.env.context.get('ar_followup_feedback'),
        )
        if not vals:
            return Log
        # sudo(): whoever chases the client is not necessarily someone with
        # write access to account.move -- a project manager posting a note on
        # an invoice they can only read must still land in the log. Logged By
        # comes from the message author, not from the sudo user, so the audit
        # trail still names a person.
        return Log.sudo().create(vals)

    def _followup_history_text(self, separator='\n'):
        """The log as plain text, oldest first.

        `_order` on the log is newest-first for the form; a report reads
        better the other way round, so it is reversed here rather than in the
        model, which the invoice form relies on.
        """
        self.ensure_one()
        methods = dict(
            self.env['account.invoice.followup.log']._fields['method'].selection)
        return separator.join(
            '%s | %s | %s%s' % (
                fields.Date.to_string(log.date) or '',
                methods.get(log.method, log.method or ''),
                log.user_id.name or '',
                ' | %s' % ' '.join((log.response or '').split()) if log.response else '',
            )
            for log in self.followup_log_ids.sorted(lambda l: (l.date, l.id))
        )

    @api.depends('invoice_date_due', 'state', 'payment_state', 'move_type')
    def _compute_ar_aging(self):
        today = fields.Date.context_today(self)
        for move in self:
            is_outstanding = (
                move.state == 'posted'
                and move.move_type == 'out_invoice'
                and move.payment_state in ('not_paid', 'partial')
            )
            if not is_outstanding or not move.invoice_date_due:
                move.invoice_age_days = 0
                move.aging_bucket = False
                continue

            due = fields.Date.to_date(move.invoice_date_due)
            delta = (today - due).days
            move.invoice_age_days = max(0, delta)

            if delta <= 0:
                move.aging_bucket = 'not_due'
            elif delta <= 30:
                move.aging_bucket = '0_30'
            elif delta <= 60:
                move.aging_bucket = '31_60'
            elif delta <= 90:
                move.aging_bucket = '61_90'
            else:
                move.aging_bucket = '90_plus'

    @api.depends('partner_id.credit_limit', 'partner_id.credit')
    def _compute_credit_hold(self):
        for move in self:
            partner = move.partner_id
            move.credit_hold = bool(
                partner and partner.credit_limit and partner.credit > partner.credit_limit
            )

    @api.model
    def _cron_refresh_ar_aging(self):
        """invoice_date_due passing, and partner.credit moving as other invoices/
        payments are posted, don't themselves trigger recompute of these stored
        fields, so a daily cron nudges outstanding invoices."""
        moves = self.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])
        moves._compute_ar_aging()
        moves._compute_credit_hold()
        # Depend on invoice_age_days, so must run after the aging refresh.
        moves._compute_ar_close_lock()
        moves._compute_ar_no_followup_flag()

    @api.constrains('ar_responsible_id', 'move_type')
    def _check_ar_responsible_required(self):
        # Invoices the system raises for itself have nobody to ask: the advance
        # invoice created when a sale order is approved would otherwise make
        # the Approve button unusable. The AR team assigns an owner on those
        # afterwards, so the flow that raises them opts out explicitly rather
        # than every programmatic create being exempt.
        if self.env.context.get('skip_ar_responsible_check'):
            return
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and not move.ar_responsible_id:
                raise ValidationError(
                    "AR Responsible is mandatory on customer invoices and credit notes. "
                    "Please set an AR Responsible before saving."
                )

    @api.constrains('sale_order_line_id', 'service_engagement_id', 'move_type')
    def _check_sale_order_line_required(self):
        """The Sale Order Line is what ties a customer invoice to an engagement.
        An engagement set directly still satisfies the rule, so retainership
        invoices — raised from a contract, never from a sale order — keep
        generating."""
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            if not move.sale_order_line_id and not move.service_engagement_id:
                raise ValidationError(
                    "Sale Order Line is mandatory on customer invoices and credit notes. "
                    "Please link this invoice to a sale order line before saving."
                )

    @api.depends('move_type', 'advance_invoice', 'retainership_contract_id',
                 'billing_stage', 'invoice_type_manual')
    def _compute_invoice_type_classification(self):
        """Classification follows what the document actually is.

        Retainer is checked before advance: an invoice raised by the
        retainership scheduler is a retainer whatever else is set on it. The
        constraint that used to police the credit-note / invoice mismatch is
        gone because move_type is now what decides it.

        `billing_stage` is what rescues the Advance bucket. The manual
        `advance_invoice` tick is set on **zero** rows in this database -- the
        `_create_advance_invoice` helper that would set it is never called from
        anywhere -- so before this every one of the 3,975 customer documents
        fell through to Completion and the dashboard's split view had nothing
        to split.

        The stage applies the firm's rule instead: **the Completion invoice is
        the last invoice on the project**, and anything raised before it is an
        Advance. Two existing signals are honoured first so that no document
        already reported as an advance loses the label -- the manual tick, and
        the Engagement dashboard's own advance resolver. See
        models/account_move_completion.py.
        """
        for move in self:
            move.invoice_type_classification = (
                move._automatic_invoice_type()
                or move.invoice_type_manual
                or move._derived_completion_type()
                or False
            )

    def _derived_completion_type(self):
        """'completion' when the billing plan already places this invoice at
        the end of the engagement, otherwise False.

        The manual tick above still wins, and the field stays editable -- this
        is only a fallback so the dashboard's split view is not left blank for
        an invoice the system has *already* worked out is the closing one.
        Without it 1,334 customer invoices carried billing_stage='completion'
        and an empty Invoice Type at the same time.
        """
        self.ensure_one()
        return 'completion' if self.billing_stage == 'completion' else False

    def _automatic_invoice_type(self):
        """The classification the document gives away by itself, or False.

        Completion is deliberately absent. A refund is a credit note, a
        document from a retainership contract is a retainer, and the first
        money on an engagement is an advance -- those three are facts. That the
        remaining invoice closes the engagement is a judgement, so the field is
        left blank for someone to make it.
        """
        self.ensure_one()
        if self.move_type == 'out_refund':
            return 'credit_note'
        if self.move_type != 'out_invoice':
            return False
        if self.retainership_contract_id:
            return 'retainer'
        if self.advance_invoice or self.billing_stage == 'advance':
            return 'advance'
        return False

    @api.depends('move_type', 'advance_invoice', 'retainership_contract_id',
                 'billing_stage')
    def _compute_invoice_type_is_automatic(self):
        for move in self:
            move.invoice_type_is_automatic = bool(move._automatic_invoice_type())


    # ------------------------------------------------------------------
    # Aged-AR close lock
    # ------------------------------------------------------------------
    # Invoices more than AR_CLOSE_LOCK_DAYS past due cannot be settled or
    # cancelled until the AR Responsible has explicitly confirmed ownership and
    # at least one follow-up has been logged against the invoice.

    ar_responsible_confirmed = fields.Boolean(
        string='AR Responsible Confirmed',
        readonly=True,
        copy=False,
        tracking=True,
        help="Set when the AR Responsible (or an accounting manager) confirms "
             "they own collection of this invoice. Cleared automatically if the "
             "AR Responsible is reassigned.",
    )
    ar_responsible_confirmed_by_id = fields.Many2one(
        'res.users',
        string='AR Confirmed By',
        readonly=True,
        copy=False,
    )
    ar_responsible_confirmed_date = fields.Datetime(
        string='AR Confirmed On',
        readonly=True,
        copy=False,
    )

    ar_close_lock_required = fields.Boolean(
        string='Aged AR Close Lock',
        compute='_compute_ar_close_lock',
        store=True,
        help="True when this invoice is more than %s days past due and still "
             "outstanding, so the settle/close gate applies." % AR_CLOSE_LOCK_DAYS,
    )
    ar_close_blocked = fields.Boolean(
        string='Close Blocked',
        compute='_compute_ar_close_lock',
        store=True,
        help="True when the aged-AR close lock applies and its conditions are "
             "not yet met.",
    )
    ar_close_block_reason = fields.Char(
        string='Close Block Reason',
        compute='_compute_ar_close_block_reason',
        help="Human-readable summary of what is still outstanding before this "
             "invoice can be settled or closed.",
    )

    def _ar_days_outstanding(self):
        """Days past the due date, computed live rather than read from the
        stored invoice_age_days (which only refreshes on the daily cron)."""
        self.ensure_one()
        if not self.invoice_date_due:
            return 0
        due = fields.Date.to_date(self.invoice_date_due)
        return (fields.Date.context_today(self) - due).days

    def _ar_close_lock_applies(self):
        """Whether the aged-AR gate applies to this invoice right now."""
        self.ensure_one()
        outstanding = (
            self.state == 'posted'
            and self.move_type == 'out_invoice'
            and self.payment_state in ('not_paid', 'partial')
        )
        return outstanding and self._ar_days_outstanding() > AR_CLOSE_LOCK_DAYS

    def _ar_close_lock_blockers(self):
        """Return the unmet close-lock conditions for this invoice.

        Empty list means the invoice is free to be settled or closed.
        """
        self.ensure_one()
        if not self._ar_close_lock_applies():
            return []
        blockers = []
        if not self.ar_responsible_id:
            blockers.append("an AR Responsible must be assigned")
        elif not self.ar_responsible_confirmed:
            blockers.append(
                "the AR Responsible (%s) must be confirmed" % self.ar_responsible_id.name
            )
        if not self.followup_log_ids:
            blockers.append(
                "at least one follow-up must be logged (post a Log note in "
                "the chatter, or mark a scheduled activity done)"
            )
        return blockers

    @api.depends(
        'invoice_age_days', 'state', 'payment_state', 'move_type',
        'ar_responsible_id', 'ar_responsible_confirmed', 'followup_log_ids',
    )
    def _compute_ar_close_lock(self):
        for move in self:
            move.ar_close_lock_required = move._ar_close_lock_applies()
            move.ar_close_blocked = bool(move._ar_close_lock_blockers())

    # Kept separate from _compute_ar_close_lock: Odoo rejects a single compute
    # method that feeds both stored and non-stored fields.
    @api.depends(
        'ar_close_lock_required', 'ar_responsible_id',
        'ar_responsible_confirmed', 'followup_log_ids',
    )
    def _compute_ar_close_block_reason(self):
        for move in self:
            blockers = move._ar_close_lock_blockers()
            move.ar_close_block_reason = "; ".join(blockers) if blockers else False

    def _check_ar_close_lock(self):
        """Raise if any invoice in self is held by the aged-AR close lock."""
        messages = []
        for move in self:
            blockers = move._ar_close_lock_blockers()
            if blockers:
                messages.append("%s (%s days past due): %s." % (
                    move.display_name,
                    move._ar_days_outstanding(),
                    ", and ".join(blockers),
                ))
        if messages:
            raise UserError(
                "This invoice is more than %s days outstanding and cannot be "
                "marked as paid or closed yet:\n\n%s\n\nUse 'Confirm AR "
                "Responsible' in the invoice header and record the collection "
                "follow-up in the Follow-up Log tab, then retry."
                % (AR_CLOSE_LOCK_DAYS, "\n".join(messages))
            )

    def action_confirm_ar_responsible(self):
        """Confirm AR ownership so an aged invoice can later be settled/closed."""
        for move in self:
            if not move.ar_responsible_id:
                raise UserError(
                    "Assign an AR Responsible on %s before confirming."
                    % move.display_name
                )
            is_manager = self.env.user.has_group('account.group_account_manager')
            if move.ar_responsible_id != self.env.user and not is_manager:
                raise UserError(
                    "Only %s (the AR Responsible) or an accounting manager can "
                    "confirm AR responsibility on %s."
                    % (move.ar_responsible_id.name, move.display_name)
                )
            move.write({
                'ar_responsible_confirmed': True,
                'ar_responsible_confirmed_by_id': self.env.user.id,
                'ar_responsible_confirmed_date': fields.Datetime.now(),
            })
            move.message_post(
                body="AR responsibility confirmed by %s for AR Responsible %s."
                     % (self.env.user.name, move.ar_responsible_id.name)
            )
        return True

    # ------------------------------------------------------------------
    # Sale Order Line: the single engagement link on the invoice
    # ------------------------------------------------------------------
    def _sale_line_for_project(self, project):
        """The one sale order line that delivers `project`.

        sudo() on purpose: the sale.order / sale.order.line record rules
        *silently* filter an inaccessible order down to nothing instead of
        raising, so without it this would quietly resolve to False for exactly
        the accounting users the field is required for.

        project.sale_line_id is checked first because it is the explicit link
        when it is set; a search on sale_order_line.project_id is what actually
        covers the database, where the relation is 1:1 (2,575 projects, none
        with more than one line pointing at them).
        """
        if not project:
            return self.env['sale.order.line']
        line = project.sudo().sale_line_id
        if line:
            return line
        return self.env['sale.order.line'].sudo().search(
            [('project_id', '=', project.id)], limit=1,
        )

    @api.depends('invoice_line_ids.sale_line_ids', 'service_engagement_id')
    def _compute_sale_order_line(self):
        """Extends project_extended_rk's compute with a project fallback.

        The invoice lines stay the primary source. When nothing on them carries
        a sale order line -- an invoice raised from a project or a task, or one
        keyed in by hand -- the engagement is used to look the line up, so the
        Sale Order Line fills itself in instead of having to be hunted for in a
        dropdown of every line the customer ever ordered.
        """
        super()._compute_sale_order_line()
        for move in self:
            if move.sale_order_line_id:
                continue
            move.sale_order_line_id = move._sale_line_for_project(
                move.service_engagement_id)

    def _set_sale_order_line(self):
        """Stamp the chosen line onto every product line that has none.

        The base inverse only touches invoice_line_ids[0], which loses the
        user's pick as soon as the compute above runs again over a multi-line
        invoice whose first line is a section or note.
        """
        for move in self:
            line = move.sale_order_line_id
            if not line:
                continue
            targets = move.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product' and not l.sale_line_ids)
            if targets:
                targets.sale_line_ids = [(6, 0, line.ids)]
            else:
                super(AccountMove, move)._set_sale_order_line()

    # ------------------------------------------------------------------
    # Service engagement, derived from the Sale Order Line
    # ------------------------------------------------------------------
    def _sync_service_engagement_from_sale_line(self):
        """Pull the engagement off the Sale Order Line's project.

        Only ever writes when the line actually resolves to a project, so an
        engagement entered by hand on a document without a sale order line is
        never blanked out.
        """
        for move in self:
            project = move.sale_order_line_id.project_id
            if project and move.service_engagement_id != project:
                move.service_engagement_id = project

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        # sale_order_line_id is itself computed from the invoice lines, so it
        # only resolves once the move (and its lines) exist.
        moves._sync_service_engagement_from_sale_line()
        return moves

    def write(self, vals):
        # Reassigning the AR Responsible invalidates a previous confirmation —
        # the new owner has to confirm for themselves.
        if 'ar_responsible_id' in vals and not vals.get('ar_responsible_confirmed'):
            new_responsible = vals['ar_responsible_id']
            to_reset = self.filtered(
                lambda m: m.ar_responsible_confirmed
                and m.ar_responsible_id.id != new_responsible
            )
            if to_reset:
                super(AccountMove, to_reset).write({
                    'ar_responsible_confirmed': False,
                    'ar_responsible_confirmed_by_id': False,
                    'ar_responsible_confirmed_date': False,
                })
        res = super().write(vals)
        # Re-point the engagement whenever the line the invoice bills against
        # changes, directly or through the invoice lines it is computed from.
        if 'sale_order_line_id' in vals or 'invoice_line_ids' in vals:
            self._sync_service_engagement_from_sale_line()
        return res

    # -- Gated settle / close entry points ------------------------------

    def action_force_register_payment(self):
        # Also covers action_register_payment, which delegates here.
        self._check_ar_close_lock()
        return super().action_force_register_payment()

    def js_assign_outstanding_line(self, line_id):
        # 'Add' on the outstanding-credits widget settles the invoice without
        # going through the payment wizard.
        self._check_ar_close_lock()
        return super().js_assign_outstanding_line(line_id)

    def button_cancel(self):
        self._check_ar_close_lock()
        return super().button_cancel()

    # ------------------------------------------------------------------
    # No-follow-up flag
    # ------------------------------------------------------------------
    # An outstanding invoice more than AR_NO_FOLLOWUP_FLAG_DAYS past due with
    # nothing at all in its Follow-up Log is flagged automatically: a red
    # banner on the invoice form, and a 'No Follow-Up Logged' filter/column on
    # the AR Aging Dashboard.

    ar_no_followup_flag = fields.Boolean(
        string='No Follow-Up Logged',
        compute='_compute_ar_no_followup_flag',
        store=True,
        help="True when this invoice is more than %s days past due and not a "
             "single follow-up has been recorded against it." % AR_NO_FOLLOWUP_FLAG_DAYS,
    )
    ar_no_followup_warning = fields.Char(
        string='No Follow-Up Warning',
        compute='_compute_ar_no_followup_warning',
        help="Live text for the red no-follow-up banner. Unlike the stored "
             "flag it is recomputed on every form load, so the banner is "
             "correct even before the daily cron has run.",
    )

    def _ar_no_followup_applies(self):
        """Whether the no-follow-up flag applies to this invoice right now."""
        self.ensure_one()
        outstanding = (
            self.state == 'posted'
            and self.move_type == 'out_invoice'
            and self.payment_state in ('not_paid', 'partial')
        )
        return (
            outstanding
            and self._ar_days_outstanding() > AR_NO_FOLLOWUP_FLAG_DAYS
            and not self.followup_log_ids
        )

    @api.depends(
        'invoice_age_days', 'invoice_date_due', 'state', 'payment_state',
        'move_type', 'followup_log_ids',
    )
    def _compute_ar_no_followup_flag(self):
        for move in self:
            move.ar_no_followup_flag = move._ar_no_followup_applies()

    # Kept separate from _compute_ar_no_followup_flag: Odoo rejects a single
    # compute method that feeds both stored and non-stored fields.
    @api.depends('ar_no_followup_flag', 'invoice_date_due', 'followup_log_ids')
    def _compute_ar_no_followup_warning(self):
        for move in self:
            if move._ar_no_followup_applies():
                move.ar_no_followup_warning = (
                    "This invoice is %s days past due and no follow-up has "
                    "been logged against it." % move._ar_days_outstanding()
                )
            else:
                move.ar_no_followup_warning = False
