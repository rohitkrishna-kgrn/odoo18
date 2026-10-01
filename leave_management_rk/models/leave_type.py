from odoo import models, fields, api
from odoo.exceptions import UserError

from .leave_period import (
    leave_month_anchor,
    leave_month_bounds,
    leave_month_label,
    shift_leave_month,
)

COUNTRIES = ('india', 'dubai')


class LeaveType(models.Model):
    _name = 'leave.type'
    _description = 'Leave Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    is_permission = fields.Boolean(string='Is Permission Leave', default=False)
    active = fields.Boolean(default=True)

    country_scope = fields.Selection([
        ('india', 'India Only'),
        ('dubai', 'Dubai (UAE) Only'),
    ], string='Applies To', help="Leave blank for a leave type shared by both India and Dubai employees.")

    accrual_mode = fields.Selection([
        ('accrue', 'Cumulative Monthly Accrual'),
        ('reset', 'Fixed Monthly Reset (no carry-forward)'),
        ('carry', 'Carried Forward As-Is (no monthly change)'),
    ], string='Monthly Behaviour', required=True, default='carry',
        help="Accrue: adds 'Monthly Accrual (Days/Hrs)' to last period's balance each leave month, "
             "optionally capped at the annual entitlement.\n"
             "Reset: balance is set to 'Monthly Reset Value' every leave month regardless of usage; "
             "nothing carries forward.\n"
             "Carry: balance simply rolls over unchanged from last period; only manual "
             "adjustments or approvals change it (e.g. Compensation Leave).")
    monthly_accrual_days = fields.Float(
        string='Monthly Accrual (Days/Hrs)', default=0.0,
        help="Used when Monthly Behaviour is 'Cumulative Monthly Accrual'.")
    cap_at_entitlement = fields.Boolean(
        string='Cap at Annual Entitlement', default=False,
        help="If set, accrual stops adding once the balance reaches the Annual Entitlement.")
    annual_entitlement = fields.Float(
        string='Annual Entitlement', default=0.0,
        help="Nominal annual entitlement in days (hours for a permission-type leave). "
             "Informational for reporting, and used as the accrual cap when enabled.")
    reset_at_year_end = fields.Boolean(
        string='Forfeit Carry-Forward at Year End', default=False,
        help="Only meaningful when Monthly Behaviour is 'Cumulative Monthly Accrual'. "
             "Balance still carries forward month to month through the calendar year as "
             "usual, but whatever is left over in December is forfeited rather than "
             "carried into January - the new year starts accruing again from the "
             "Starting Balance.")
    monthly_reset_value = fields.Float(
        string='Monthly Reset Value', default=0.0,
        help="Used when Monthly Behaviour is 'Fixed Monthly Reset'.")
    initial_balance = fields.Float(
        string='Starting Balance', default=0.0,
        help="Seed balance used the first time a leave month is opened for a user/leave type "
             "with no prior balance row.")
    allows_half_day = fields.Boolean(string='Allows Half Day', default=False)
    requires_dha_certificate = fields.Boolean(
        string='Requires DHA Certificate',
        default=False,
        help="If set, a DHA Sick Leave Certificate is mandatory when 2 or more days are requested.")
    dubai_annual_pool = fields.Boolean(
        string='Dubai Uses Annual Pool', default=False,
        help="Only meaningful for a leave type shared by both countries (blank "
             "'Applies To'). Dubai employees ignore this type's own Monthly "
             "Behaviour/Monthly Reset Value (which continue to apply unchanged for "
             "India) and instead carry a pool forward from leave month to leave "
             "month, seeded from Annual Entitlement, that resets every January — "
             "e.g. Sick Leave: India resets to 1 day every leave month, Dubai "
             "carries a 45-day/year pool.")
    restart_accrual_after_leave = fields.Boolean(
        string='Restart Monthly Accrual After Each Completed Leave', default=False,
        help="For a type with Monthly Behaviour = 'Cumulative Monthly Accrual' "
             "(e.g. Dubai's Annual Leave). Instead of accruing continuously from "
             "whenever the employee became eligible, accrual only starts counting "
             "from the leave month right after their most recently COMPLETED "
             "approved request of this type ended - e.g. a request ending "
             "19 Feb starts a fresh accrual cycle on 1 Mar, building back up at "
             "Monthly Accrual (Days/Hrs) per month from zero, capped at Annual "
             "Entitlement as usual. Every time a newer request of this type "
             "completes, the cycle restarts again from the month after that one. "
             "An employee with NO completed request of this type yet accrues "
             "nothing automatically - HR sets their balance manually via Employee "
             "Leave Balance until their first cycle begins, rather than the "
             "system guessing a starting figure for them.")
    balance_unit_period = fields.Selection([
        ('year', 'Per Year'),
        ('month', 'Per Month'),
    ], string='Balance Unit Period', default='year', required=True,
        help="Cosmetic only - how the Employee Leave Balance popup labels this "
             "type's unit (e.g. 'days/year' vs 'days/month'), purely to tell HR "
             "at a glance whether a balance accumulates across the leave year "
             "(Casual Leave, Compensation Leave) or is a fixed month-to-month "
             "figure (Sick Leave, India). Doesn't affect any accrual math. "
             "Dubai's dubai_annual_pool types always display 'Per Year' "
             "regardless of this field, since the pool itself is annual even "
             "when the same leave type resets monthly for India.")


class LeaveBalance(models.Model):
    _name = 'leave.balance'
    _description = 'Leave Balance per User per Leave Type'

    user_id = fields.Many2one('res.users', string='User', required=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    balance = fields.Float(string='Balance', default=0.0)
    date = fields.Date(
        string='Leave Month',
        help="Anchor of the leave month this balance belongs to: the 1st of the "
             "month the period is named after. The period itself runs from the "
             "26th of the previous month to the 25th of this one.")
    period_start = fields.Date(
        string='Period Start', compute='_compute_period', store=False)
    period_end = fields.Date(
        string='Period End', compute='_compute_period', store=False)
    period_label = fields.Char(
        string='Leave Period', compute='_compute_period', store=False)
    is_current_period = fields.Boolean(
        string='Current Leave Month',
        compute='_compute_is_current_period',
        search='_search_is_current_period',
        store=False)

    _sql_constraints = [
        ('user_leave_unique', 'unique(user_id, leave_type_id, date)', 'Leave balance already exists for this user, leave type, and date.'),
    ]

    @api.depends('date')
    def _compute_period(self):
        for rec in self:
            if rec.date:
                rec.period_start, rec.period_end = leave_month_bounds(rec.date)
                rec.period_label = leave_month_label(rec.date)
            else:
                rec.period_start = rec.period_end = False
                rec.period_label = ''

    @api.depends('date')
    def _compute_is_current_period(self):
        current = leave_month_anchor(fields.Date.today())
        for rec in self:
            rec.is_current_period = rec.date == current

    def _search_is_current_period(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError("Unsupported search on 'Current Leave Month'.")
        current = leave_month_anchor(fields.Date.today())
        matches = (operator == '=') == bool(value)
        return [('date', '=' if matches else '!=', current)]

    @api.depends('user_id', 'leave_type_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.user_id.name or '', rec.leave_type_id.name or '']
            if rec.date:
                parts.append(rec.date.strftime('%B %Y'))
            rec.display_name = ' - '.join(p for p in parts if p)

    @api.model
    def current_leave_month(self, any_date=None):
        """Anchor of the leave month covering ``any_date`` (default: today)."""
        return leave_month_anchor(any_date or fields.Date.today())

    def _applicable_leave_types(self, country):
        """Leave types usable by ``country``: shared (blank scope) + scoped to it."""
        if country not in COUNTRIES:
            # No Country For Leave Model set: only Permission (3 hrs/month,
            # shared by every country) applies, so nobody is left without it.
            return self.env['leave.type'].search([
                ('is_permission', '=', True), ('country_scope', '=', False),
            ])
        return self.env['leave.type'].search([
            '|', ('country_scope', '=', False), ('country_scope', '=', country),
        ])

    @api.model
    def _permission_default(self, user, leave_type, anchor):
        """Permission hours left for a leave month that has no row yet: the
        monthly default (3) minus whatever the user already had approved in
        that 26th-25th window."""
        start, end = leave_month_bounds(anchor)
        taken = sum(self.env['leave.request'].sudo().search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', start),
            ('start_date', '<=', end),
        ]).mapped('hours_requested'))
        return max(leave_type.monthly_reset_value - taken, 0.0)

    @api.model
    def _get_permission_balance(self, user, leave_type, anchor):
        """Read-only: the stored balance, or the month's default if no row."""
        row = self.sudo().search([
            ('user_id', '=', user.id), ('leave_type_id', '=', leave_type.id),
            ('date', '=', anchor)], limit=1)
        if row:
            return row.balance
        return self._permission_default(user, leave_type, anchor)

    @api.model
    def _ensure_permission_row(self, user, leave_type, anchor):
        """The month's Permission row, created from the default if missing."""
        row = self.sudo().search([
            ('user_id', '=', user.id), ('leave_type_id', '=', leave_type.id),
            ('date', '=', anchor)], limit=1)
        if not row:
            row = self.sudo().create({
                'user_id': user.id, 'leave_type_id': leave_type.id, 'date': anchor,
                'balance': self._permission_default(user, leave_type, anchor),
            })
        return row

    def _leave_eligible_users(self):
        """India/Dubai users who should accrue leave: active employees with a
        Country For Leave Model set, regardless of whether their own login
        (res.users.active) is enabled.

        Country For Leave Model only lives on res.users, so an employee still
        needs a user record to be reachable at all — but most staff here have
        one created and configured, then archived once portal/backend access
        was revoked, which used to silently drop them out of every leave
        automation entirely. Searching through the still-active hr.employee
        instead, and reading its user_id (a plain field access, not a new
        search, so it isn't filtered by the user's own active flag), keeps
        that from mattering: an archived login no longer means "no leave
        balance".
        """
        employees = self.env['hr.employee'].search([
            ('active', '=', True),
            ('user_id', '!=', False),
        ])
        # Users with no country are kept on purpose: they get Permission only
        # (see _applicable_leave_types).
        return employees.mapped('user_id')

    def _restart_cycle_anchor(self, user, leave_type):
        """Leave month a ``restart_accrual_after_leave`` type's accrual cycle
        currently counts from for ``user`` - the leave month right after the
        one their most recently COMPLETED (end_date already in the past)
        APPROVED request of this type ended in. None if they have no
        completed request of this type yet - callers must not auto-accrue
        anything in that case (see the field's help).

        Always looks this up fresh from leave.request rather than storing it,
        so a newer completed request automatically re-anchors the cycle the
        next time this runs, with no separate bookkeeping that could drift
        out of sync with the actual leave history.
        """
        last_request = self.env['leave.request'].search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('state', '=', 'approved'),
            ('end_date', '<', fields.Date.today()),
        ], order='end_date desc', limit=1)
        if not last_request:
            return None
        return shift_leave_month(leave_month_anchor(last_request.end_date), 1)

    def _restart_accrual_projected_balance(self, user, leave_type, as_of=None):
        """Live estimate of a ``restart_accrual_after_leave`` type's balance
        as of ``as_of`` (default: today), for display before the monthly cron
        has actually written a leave.balance row for the period in progress -
        e.g. the Employee Leave Balance wizard opening for a period the cron
        hasn't reached yet. Deliberately mirrors exactly what
        _get_last_balance/_next_period_balance will themselves compute once
        the cron does run, so the two can never show different numbers for
        the same day.

        0.0 if the employee has no completed request of this type yet - see
        the field's help; nothing is projected for them until their first
        cycle begins.
        """
        cycle_start = self._restart_cycle_anchor(user, leave_type)
        current_anchor = leave_month_anchor(as_of or fields.Date.today())
        if not cycle_start or current_anchor < cycle_start:
            return 0.0
        months_elapsed = (
            (current_anchor.year - cycle_start.year) * 12
            + (current_anchor.month - cycle_start.month) + 1
        )
        accrued = months_elapsed * leave_type.monthly_accrual_days
        if leave_type.cap_at_entitlement and leave_type.annual_entitlement:
            accrued = min(accrued, leave_type.annual_entitlement)
        field = 'hours_requested' if leave_type.is_permission else 'days_requested'
        taken = self.env['leave.request'].search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', cycle_start),
        ])
        return accrued - sum(taken.mapped(field))

    def _get_last_balance(self, user, leave_type, before_date):
        """Balance carried into the period starting ``before_date``.

        Looks strictly at rows dated *before* ``before_date`` so re-running the
        engine for the same period (e.g. the monthly cron and the year-end
        reset landing on the same boundary) never picks up a row it just wrote
        itself and double-accrues. Falls back to the leave type's configured
        starting balance when no prior row exists at all.

        A leave type with ``reset_at_year_end`` forfeits whatever carried
        through December the moment January opens: it deliberately ignores
        December's row and restarts from the Starting Balance, the one point
        where "no carry-forward across periods" legitimately differs from
        "no carry-forward within the engine's own idempotency rule" above.

        A ``dubai_annual_pool`` type forfeits the same way for a Dubai user,
        but seeded from Annual Entitlement rather than Starting Balance — its
        own Monthly Behaviour/Starting Balance describe India's config on a
        type shared by both countries (see leave.type's field help).

        A ``restart_accrual_after_leave`` type forfeits the same way again,
        right on its own cycle's first period (see _restart_cycle_anchor) -
        seeded from zero, since the whole point is to build back up from
        nothing rather than carry over whatever was left from before the
        restart. Callers must have already confirmed a cycle anchor exists
        for this (user, leave_type) before calling this at all (see
        _apply_period_accrual) - a type with no completed leave yet is never
        auto-accrued in the first place.
        """
        dubai_pool = leave_type.dubai_annual_pool and user.country == 'dubai'
        if (leave_type.reset_at_year_end or dubai_pool) and before_date.month == 1:
            return leave_type.annual_entitlement if dubai_pool else leave_type.initial_balance
        if leave_type.restart_accrual_after_leave:
            cycle_start = self._restart_cycle_anchor(user, leave_type)
            if cycle_start and before_date == cycle_start:
                return 0.0
        last = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('date', '<', before_date),
        ], order='date desc', limit=1)
        if last:
            return last.balance
        return leave_type.annual_entitlement if dubai_pool else leave_type.initial_balance

    def _next_period_balance(self, leave_type, last_balance, user):
        if leave_type.dubai_annual_pool and user.country == 'dubai':
            # Carries forward unchanged; only leave approvals move it, same as
            # 'carry' mode — this type's own accrual_mode describes India's
            # config instead (see dubai_annual_pool's help).
            return last_balance
        if leave_type.accrual_mode == 'reset':
            return leave_type.monthly_reset_value
        if leave_type.accrual_mode == 'accrue':
            new_balance = last_balance + leave_type.monthly_accrual_days
            if leave_type.cap_at_entitlement and leave_type.annual_entitlement:
                new_balance = min(new_balance, leave_type.annual_entitlement)
            return new_balance
        # 'carry': rolls over unchanged; only approvals/manual edits move it.
        return last_balance

    @api.model
    def _is_manual_carry_type(self, user, leave_type):
        """India accruing type (Casual Leave): +N every month, and whatever
        the balance is at the moment - after a deduction or a manual edit -
        is the base the following months build on."""
        return (
            user.country == 'india'
            and leave_type.accrual_mode == 'accrue'
            and not leave_type.restart_accrual_after_leave
            and not leave_type.dubai_annual_pool
        )

    def write(self, vals):
        """A change to an accruing India balance (manual edit in Employee Leave
        Balance, an approval deduction or a cancel refund) shifts every later
        row of the same calendar year by the same amount, so months already
        projected keep "modified balance + 1 per month" instead of going
        stale. Next January is a fresh reset and is left alone."""
        if 'balance' not in vals or self.env.context.get('no_balance_cascade'):
            return super().write(vals)
        deltas = {r.id: 0.0 for r in self}
        for r in self:
            deltas[r.id] = vals['balance'] - (r.balance or 0.0)
        res = super().write(vals)
        for r in self:
            delta = deltas[r.id]
            if not delta or not r.date or not self._is_manual_carry_type(r.user_id, r.leave_type_id):
                continue
            later = self.with_context(no_balance_cascade=True).search([
                ('user_id', '=', r.user_id.id),
                ('leave_type_id', '=', r.leave_type_id.id),
                ('date', '>', r.date),
                ('date', '<=', r.date.replace(month=12, day=31)),
            ])
            for row in later:
                row.balance = (row.balance or 0.0) + delta
        return res

    def _apply_period_accrual(self, period_anchor, users=None):
        """Open ``period_anchor`` for every applicable (user, leave type) pair.

        Same logic regardless of which cron calls it or which month it is —
        there is no special-cased "January reset"; a fixed-value leave type
        resets every period and an accruing one keeps accruing, January
        included, so nothing is ever force-reset in a way that silently
        forfeits a balance the requirements don't say should be forfeited.

        A ``restart_accrual_after_leave`` type is the one exception: it is
        skipped entirely (no leave.balance row touched at all) for any user
        with no completed request of this type yet, or whose cycle hasn't
        started as of this period - see the field's help. HR manages their
        balance manually via Employee Leave Balance until then.
        """
        if users is None:
            users = self._leave_eligible_users()

        for user in users:
            for leave_type in self._applicable_leave_types(user.country):
                if leave_type.restart_accrual_after_leave:
                    cycle_start = self._restart_cycle_anchor(user, leave_type)
                    if not cycle_start or period_anchor < cycle_start:
                        continue
                if self._is_manual_carry_type(user, leave_type) and self.search_count([
                    ('user_id', '=', user.id),
                    ('leave_type_id', '=', leave_type.id),
                    ('date', '=', period_anchor),
                ]):
                    # Row already exists (projected earlier, or set by hand in
                    # Employee Leave Balance): never overwrite it. Manual
                    # edits and deductions are propagated to the later rows
                    # by leave.balance.write, so it is already correct.
                    continue
                last_balance = self._get_last_balance(user, leave_type, period_anchor)
                new_balance = self._next_period_balance(leave_type, last_balance, user)
                self._update_balance(user, leave_type, period_anchor, new_balance)

    @api.model
    def update_monthly_leave_balances(self):
        # Runs on the 26th: that date already belongs to the new leave month,
        # so the anchor helper returns the period being opened.
        first_of_this_month = leave_month_anchor(fields.Date.today())
        self._apply_period_accrual(first_of_this_month)

    def _update_balance(self, user, leave_type, balance_date, balance):
        rec = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('date', '=', balance_date)
        ], limit=1)
        if rec:
            rec.with_context(no_balance_cascade=True).balance = balance
        else:
            self.create({
                'user_id': user.id,
                'leave_type_id': leave_type.id,
                'date': balance_date,
                'balance': balance,
            })

    def _update_balance_and_cascade(self, user, leave_type, balance_date, balance):
        """Like _update_balance, but a change to an accruing India balance is
        carried into the later months already projected (see write())."""
        rec = self.search([
            ('user_id', '=', user.id),
            ('leave_type_id', '=', leave_type.id),
            ('date', '=', balance_date),
        ], limit=1)
        if rec:
            rec.balance = balance
        else:
            self.create({
                'user_id': user.id,
                'leave_type_id': leave_type.id,
                'date': balance_date,
                'balance': balance,
            })

    @api.model
    def update_user_balance_on_country_change(self, user):
        if user.country not in COUNTRIES:
            return
        current_anchor = leave_month_anchor(fields.Date.today())
        for i in range(4):
            month_date = shift_leave_month(current_anchor, i)
            self._apply_period_accrual(month_date, users=user)

    @api.model
    def reset_leave_balances_dec31(self):
        """Year-end reset - seeds the January leave month (26 Dec -> 25 Jan).

        The cron now fires on 25 Dec 23:59 rather than 31 Dec 23:59, keeping it
        immediately ahead of the monthly accrual that opens the January period
        at 26 Dec 00:00 - the same ordering it had against the 1 Jan cron.
        Kept working whichever side of the 26th it is triggered from.

        Uses the same period-accrual engine as any other month: there is no
        separate "reset to defaults" step here any more, since each leave
        type's own Monthly Behaviour already says what should happen to it
        every period, January included.
        """
        anchor = leave_month_anchor(fields.Date.today())
        jan_first_next_year = (
            anchor if anchor.month == 1
            else anchor.replace(year=anchor.year + 1, month=1, day=1)
        )
        self._apply_period_accrual(jan_first_next_year)

    @api.model
    def action_manual_reset_leaves(self):
        """Manual reset button - System Admin only.

        Recomputes every balance for the leave month in progress from scratch
        and from approved leave.request history, so it always lands on the
        same figure the engine would have reached with no manual edits:

        - Accruing India type (Casual Leave): monthly accrual x leave months
          elapsed since January, minus approved days in the leave year
          (26 Dec -> today's period end).
        - Yearly 'reset' type (Loss of Pay): its yearly value minus approved
          days in the leave year. Monthly 'reset' types (India Sick,
          Permission): monthly value minus approved in this leave month.
        - Dubai Sick pool: Annual Entitlement minus approved in the year.
        - 'carry' types (Compensation Leave): back to Starting Balance (0).
        - Dubai Annual Leave (restart-after-leave) is left untouched.
        """
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only System Administrators can perform manual leave resets.")
        # Gate is the System Admin check above; the writes below must not
        # depend on that admin also being an HR Manager, nor on record rules
        # hiding other employees' requests from the totals.
        self = self.sudo()

        first_of_month = leave_month_anchor(fields.Date.today())
        month_start, month_end = leave_month_bounds(first_of_month)
        # Leave year = 26 Dec -> 25 Dec; January's anchor opens it.
        year_start, _unused = leave_month_bounds(first_of_month.replace(month=1))
        users = self._leave_eligible_users()
        Request = self.env['leave.request']

        for user in users:
            for leave_type in self._applicable_leave_types(user.country):
                if leave_type.restart_accrual_after_leave:
                    # Dubai Annual Leave builds up from its own cycle; there
                    # is no fixed "default" to force it to.
                    continue
                dubai_pool = leave_type.dubai_annual_pool and user.country == 'dubai'
                per_year = dubai_pool or (
                    leave_type.balance_unit_period == 'year'
                    and not leave_type.is_permission
                )
                window_start = year_start if per_year else month_start
                field = 'hours_requested' if leave_type.is_permission else 'days_requested'
                taken = sum(Request.search([
                    ('user_id', '=', user.id),
                    ('leave_type_id', '=', leave_type.id),
                    ('state', '=', 'approved'),
                    ('start_date', '>=', window_start),
                    ('start_date', '<=', month_end),
                ]).mapped(field))

                if dubai_pool:
                    seed = leave_type.annual_entitlement - taken
                elif leave_type.accrual_mode == 'accrue':
                    # +N per leave month since January, less approved leave
                    # taken in the leave year so far.
                    accrued = leave_type.monthly_accrual_days * first_of_month.month
                    if leave_type.cap_at_entitlement and leave_type.annual_entitlement:
                        accrued = min(accrued, leave_type.annual_entitlement)
                    seed = accrued - taken
                elif leave_type.accrual_mode == 'reset':
                    seed = leave_type.monthly_reset_value - taken
                elif leave_type.cap_at_entitlement:
                    seed = leave_type.annual_entitlement - taken
                else:
                    # 'carry' types (Compensation Leave) go back to Starting Balance.
                    seed = leave_type.initial_balance
                self._update_balance_and_cascade(user, leave_type, first_of_month, seed)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Leave Reset Complete',
                'message': 'All leave balances have been reset to defaults.',
                'type': 'success',
            }
        }
