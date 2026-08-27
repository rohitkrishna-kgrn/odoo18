from datetime import timedelta

from odoo import models, fields, api, _

from markupsafe import Markup

# Days past due beyond which a single outstanding customer invoice puts its
# customer on Credit Hold. Deliberately the same threshold as
# AR_CLOSE_LOCK_DAYS in account_move.py — an invoice that can no longer be
# settled or closed without AR sign-off is the same invoice that stops the
# client taking on new work.
CREDIT_HOLD_OVERDUE_DAYS = 180


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # The flag itself. Written only by the evaluation below (cron, invoice
    # payment, or the manual "Re-evaluate" button) — there is no supported way
    # to tick it by hand, because a hand-set flag would be cleared again by the
    # next sweep and give a false sense of control.
    credit_hold = fields.Boolean(
        string='Credit Hold',
        default=False,
        copy=False,
        tracking=True,
        help="Set automatically when this customer has at least one posted "
             "invoice more than %s days past its due date. Cleared "
             "automatically once every such invoice is paid or credited."
             % CREDIT_HOLD_OVERDUE_DAYS,
    )

    credit_hold_date = fields.Datetime(
        string='Credit Hold Triggered On',
        readonly=True,
        copy=False,
        help="When the current hold was placed. Cleared when the hold is released.",
    )

    credit_hold_release_date = fields.Datetime(
        string='Credit Hold Released On',
        readonly=True,
        copy=False,
        help="When the most recent hold was released because every triggering "
             "invoice had been settled.",
    )

    # Live set of the invoices currently keeping this customer on hold. Kept in
    # step by every evaluation, so it shrinks as invoices are paid and the hold
    # lifts when it empties. The frozen record of what triggered a *particular*
    # hold lives on the event log instead.
    credit_hold_invoice_ids = fields.Many2many(
        'account.move',
        'res_partner_credit_hold_move_rel',
        'partner_id',
        'move_id',
        string='Invoices Causing Hold',
        readonly=True,
        copy=False,
    )

    credit_hold_amount = fields.Monetary(
        string='Overdue Amount On Hold',
        currency_field='currency_id',
        readonly=True,
        copy=False,
        help="Total still outstanding on the invoices causing the hold.",
    )

    credit_hold_max_age_days = fields.Integer(
        string='Oldest Overdue (Days)',
        readonly=True,
        copy=False,
        help="Age of the most overdue invoice causing the hold, in days past due.",
    )

    credit_hold_event_ids = fields.One2many(
        'res.partner.credit.hold.event',
        'partner_id',
        string='Credit Hold History',
        readonly=True,
    )

    credit_hold_override_ids = fields.One2many(
        'res.partner.credit.hold.override',
        'partner_id',
        string='Credit Hold Overrides',
        readonly=True,
    )

    credit_hold_override_available_count = fields.Integer(
        string='Unused Overrides',
        compute='_compute_credit_hold_override_available_count',
    )

    credit_hold_warning = fields.Char(
        string='Credit Hold Warning',
        compute='_compute_credit_hold_warning',
        help="Live banner text. Recomputed on every form load so it is correct "
             "even before the daily sweep has run.",
    )

    @api.depends('credit_hold_override_ids.state')
    def _compute_credit_hold_override_available_count(self):
        for partner in self:
            partner.credit_hold_override_available_count = len(
                partner.credit_hold_override_ids.filtered(
                    lambda o: o.state == 'available'
                )
            )

    @api.depends('credit_hold', 'credit_hold_amount', 'credit_hold_max_age_days',
                 'credit_hold_date')
    def _compute_credit_hold_warning(self):
        for partner in self:
            if not partner.credit_hold:
                partner.credit_hold_warning = False
                continue
            partner.credit_hold_warning = _(
                "CREDIT HOLD — %(count)s invoice(s) totalling %(amount)s are more "
                "than %(days)s days overdue (oldest %(age)s days). New projects and "
                "new proposals for this customer are blocked until the balance is "
                "cleared or a Managing Partner records an override.",
                count=len(partner.credit_hold_invoice_ids),
                amount=partner.credit_hold_amount,
                days=CREDIT_HOLD_OVERDUE_DAYS,
                age=partner.credit_hold_max_age_days,
            )

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _credit_hold_overdue_invoices(self):
        """The posted customer invoices past the hold threshold for this
        customer, taken across the whole commercial entity so a debt sitting on
        a child contact still holds the parent.

        active_test is switched off deliberately: account_extended_rk added an
        `active` field to account.move for the stale-draft sweep, and a credit
        control rule that could be side-stepped by archiving the invoice would
        not be worth much.
        """
        self.ensure_one()
        cutoff = fields.Date.context_today(self) - timedelta(days=CREDIT_HOLD_OVERDUE_DAYS)
        return self.env['account.move'].with_context(active_test=False).search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('commercial_partner_id', '=', self.commercial_partner_id.id),
            ('invoice_date_due', '!=', False),
            ('invoice_date_due', '<', cutoff),
        ], order='invoice_date_due asc')

    def _credit_hold_evaluate(self, silent=False):
        """Place, refresh or release the hold on each customer in self.

        Everything routes through here — the cron, the payment hook and the
        manual button — so there is exactly one place that decides whether a
        customer is on hold. `silent` suppresses notifications while still
        writing the flag and the history, which is what the go-live backfill
        needs.
        """
        today = fields.Date.context_today(self)

        # Holds belong on the commercial entity, never on a child contact.
        # sudo throughout: this runs from the nightly cron, but also off the
        # back of a payment reconciliation performed by whoever happened to
        # register the payment, and they will not have write access to the
        # customer record or the audit log.
        for partner in self.mapped('commercial_partner_id').sudo():
            overdue = partner._credit_hold_overdue_invoices()

            if overdue:
                amount = sum(overdue.mapped('amount_residual'))
                max_age = max(
                    (today - fields.Date.to_date(move.invoice_date_due)).days
                    for move in overdue
                )
                was_held = partner.credit_hold
                partner.write({
                    'credit_hold': True,
                    'credit_hold_invoice_ids': [fields.Command.set(overdue.ids)],
                    'credit_hold_amount': amount,
                    'credit_hold_max_age_days': max_age,
                    # Only stamped when the hold actually starts, so the date
                    # keeps meaning "held since" across daily refreshes.
                    'credit_hold_date': partner.credit_hold_date or fields.Datetime.now(),
                    'credit_hold_release_date': False,
                })
                if not was_held:
                    partner._credit_hold_log_event('hold', overdue, amount, max_age, silent=silent)
                    if not silent:
                        partner._credit_hold_notify('hold', overdue)

            elif partner.credit_hold:
                # Nothing left over the threshold: release.
                cleared = partner.credit_hold_invoice_ids
                partner.write({
                    'credit_hold': False,
                    'credit_hold_invoice_ids': [fields.Command.clear()],
                    'credit_hold_amount': 0.0,
                    'credit_hold_max_age_days': 0,
                    'credit_hold_date': False,
                    'credit_hold_release_date': fields.Datetime.now(),
                })
                partner._credit_hold_log_event('release', cleared, 0.0, 0, silent=silent)
                if not silent:
                    partner._credit_hold_notify('release', cleared)

        return True

    def action_credit_hold_reevaluate(self):
        """Manual re-check from the customer form."""
        self._credit_hold_evaluate()
        return True

    @api.model
    def _cron_credit_hold_evaluate(self):
        """Daily sweep.

        Two populations have to be looked at: customers who already carry a
        hold (they may now qualify for release) and customers with an invoice
        that has just crossed the threshold. Anything else cannot have changed
        state since yesterday.
        """
        cutoff = fields.Date.context_today(self) - timedelta(days=CREDIT_HOLD_OVERDUE_DAYS)
        newly_overdue = self.env['account.move'].with_context(active_test=False).search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_date_due', '!=', False),
            ('invoice_date_due', '<', cutoff),
        ]).mapped('commercial_partner_id')

        already_held = self.search([('credit_hold', '=', True)])

        (newly_overdue | already_held)._credit_hold_evaluate()
        return True

    # ------------------------------------------------------------------
    # History and notification
    # ------------------------------------------------------------------

    def _credit_hold_log_event(self, event_type, invoices, amount, max_age, silent=False):
        """Freeze what the hold/release looked like at this moment.

        The invoice numbers, amounts and due dates are copied into the event as
        text as well as linked, so the history still reads correctly years later
        when those invoices have been paid down to nothing.
        """
        self.ensure_one()
        self.env['res.partner.credit.hold.event'].sudo().create({
            'partner_id': self.id,
            'event_type': event_type,
            'event_date': fields.Datetime.now(),
            'invoice_ids': [fields.Command.set(invoices.ids)],
            'amount': amount,
            'max_age_days': max_age,
            'is_backfill': silent,
            'detail': self._credit_hold_invoice_detail(invoices),
        })

    def _credit_hold_invoice_detail(self, invoices):
        """Plain-text snapshot: number, overdue amount, due date, age."""
        today = fields.Date.context_today(self)
        lines = []
        for move in invoices:
            due = fields.Date.to_date(move.invoice_date_due) if move.invoice_date_due else None
            lines.append("%s | %s %s | due %s | %s days overdue" % (
                move.name,
                move.currency_id.symbol or move.currency_id.name or '',
                '{:,.2f}'.format(move.amount_residual),
                due or '-',
                (today - due).days if due else '-',
            ))
        return "\n".join(lines)

    def _credit_hold_recipients(self):
        """Project Managers on the customer's work, plus the sales team users.

        PMs come from two places, unioned: the Project Manager field on the
        invoices behind the hold (which account_move_project_team_rk derives
        from the sale order lines) and the manager of any active project for
        this customer.

        "The relevant sales team" is taken from the triggering invoices, since
        a customer record carries no sales team of its own; users are matched
        on the Sales Team Access fields of their own user record.
        """
        self.ensure_one()
        invoices = self.credit_hold_invoice_ids

        managers = invoices.mapped('project_manager_ids')
        projects = self.env['project.project'].search([
            ('partner_id', 'child_of', self.id),
        ])
        managers |= projects.mapped('user_id')

        teams = invoices.mapped('team_id')
        if not teams:
            # Fall back to the customer's most recent order, then to nothing —
            # better to notify only the PMs than to spray every sales user.
            last_order = self.env['sale.order'].search(
                [('partner_id', 'child_of', self.id), ('team_id', '!=', False)],
                order='date_order desc', limit=1,
            )
            teams = last_order.team_id

        sales_users = self.env['res.users']
        if teams:
            sales_users = self.env['res.users'].search([
                '|',
                ('sale_team_id', 'in', teams.ids),
                ('crm_team_ids', 'in', teams.ids),
            ])

        recipients = managers | sales_users
        # Never address archived accounts or portal/public users.
        return recipients.filtered(lambda u: u.active and not u.share)

    def _credit_hold_notify(self, event_type, invoices):
        """Post to the customer's chatter addressed to the PMs and sales team.

        message_post with explicit partner_ids gives both the Odoo inbox
        notification and the outgoing email, which is how the rest of this
        module notifies people.
        """
        self.ensure_one()
        recipients = self._credit_hold_recipients()
        if not recipients:
            self.message_post(body=_(
                "Credit Hold %s, but no Project Manager or sales team user "
                "could be identified to notify.",
                _("placed") if event_type == 'hold' else _("released"),
            ))
            return

        if event_type == 'hold':
            body = Markup(
                "<p><b>%s</b></p><p>%s</p>%s<p>%s</p>"
            ) % (
                _("Credit Hold placed on %s", self.display_name),
                _("The following invoice(s) are more than %s days past due.",
                  CREDIT_HOLD_OVERDUE_DAYS),
                self._credit_hold_invoice_table(invoices),
                _("Restrictions now in force: new projects cannot be created for "
                  "this customer, and new proposals cannot be created or submitted "
                  "for approval. A Managing Partner can authorise a single "
                  "exception, with a reason, from the customer form."),
            )
        else:
            body = Markup(
                "<p><b>%s</b></p><p>%s</p>%s<p>%s</p>"
            ) % (
                _("Credit Hold released on %s", self.display_name),
                _("Every invoice that caused the hold has been settled, and no "
                  "invoice remains more than %s days past due.",
                  CREDIT_HOLD_OVERDUE_DAYS),
                self._credit_hold_invoice_table(invoices),
                _("New projects and proposals for this customer are allowed again."),
            )

        self.message_post(
            body=body,
            partner_ids=recipients.mapped('partner_id').ids,
            subtype_xmlid='mail.mt_comment',
        )

    def _credit_hold_invoice_table(self, invoices):
        self.ensure_one()
        if not invoices:
            return Markup("")
        today = fields.Date.context_today(self)
        rows = Markup("")
        for move in invoices:
            due = fields.Date.to_date(move.invoice_date_due) if move.invoice_date_due else None
            rows += Markup(
                "<tr><td>%s</td><td style='text-align:right'>%s %s</td>"
                "<td>%s</td><td style='text-align:right'>%s</td></tr>"
            ) % (
                move.name,
                move.currency_id.symbol or move.currency_id.name or '',
                '{:,.2f}'.format(move.amount_residual),
                due or '-',
                (today - due).days if due else '-',
            )
        return Markup(
            "<table class='table table-sm'><thead><tr>"
            "<th>%s</th><th style='text-align:right'>%s</th><th>%s</th>"
            "<th style='text-align:right'>%s</th></tr></thead><tbody>%s</tbody></table>"
        ) % (
            _("Invoice"), _("Overdue Amount"), _("Due Date"), _("Age (days)"), rows,
        )

    # ------------------------------------------------------------------
    # Override entry point
    # ------------------------------------------------------------------

    def action_credit_hold_override(self):
        """Open the Managing Partner override wizard for this customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Managing Partner Credit Hold Override"),
            'res_model': 'res.partner.credit.hold.override',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.commercial_partner_id.id},
        }
