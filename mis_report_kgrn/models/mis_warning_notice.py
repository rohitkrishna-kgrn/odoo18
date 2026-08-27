"""
KGRN Performance Management — Warning Notice counter (HR-PMS-001 §Escalation).

The counter itself already lives in ``mis.performance.line`` as
``consecutive_below_target`` — the number of consecutive months in which
Payment Collected fell short of the location minimum (Monthly CTC x 3 UAE /
x 5 India), reset to zero by any On Track month.  For a new joiner that
minimum is the ramped one — 1x CTC in their first month, 2x in their second —
so the ramp-up carries all the way through to escalation and nobody is
counted below a target that has not taken effect for them yet.  This module
turns that read-only number into the escalation actions the policy asks for:

    Month 1  — nothing in the system (verbal flag, handled off-system).
    Month 2  — an automatic flag for HR: a ``mis.warning.notice`` record in
               state "Flagged for HR" plus a To-Do activity on every member
               of the MIS HR group, so it lands in their Odoo inbox.
    Month 3+ — the same record advances to a DRAFT Warning Notice: the notice
               body is generated (employee, month-by-month shortfall table,
               policy clause) for HR to review, edit and then issue.  Nothing
               is ever issued automatically — "Issue Notice" is a human click.

    Reset   — the first On Track month closes the open case ("Closed —
               Minimum Met") and the counter starts again from zero.

Counter start floor
-------------------
``mis.performance.line`` is a rolling 12-month view, so on the day this
feature goes live most staff already carry a long below-target streak (the
firm's collection data is sparse from March 2026 onward).  Issuing the whole
firm a 3rd-month Warning Notice for months that pre-date the system would be
wrong, so the effective counter is capped at the number of months since the
``mis_report_kgrn.escalation_counter_start`` config parameter.  Clear that
parameter to score the full history instead.
"""

import logging

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Consecutive below-target months that trigger each escalation step.
FLAG_THRESHOLD = 2      # auto-flag for HR
NOTICE_THRESHOLD = 3    # draft Warning Notice for HR to review and issue

# A month counts as below target when its Status is "At Risk" or
# "Below Minimum"; "On Track" and "N/A" (no CTC on record) both reset it.
ON_TRACK_STATUSES = ('On Track', 'N/A')

OPEN_STATES = ('flagged', 'draft', 'issued')

COUNTER_START_PARAM = 'mis_report_kgrn.escalation_counter_start'


class MisWarningNoticeMonth(models.Model):
    """One below-target month inside a case's current streak — the evidence
    table that goes on the Warning Notice."""
    _name = 'mis.warning.notice.month'
    _description = 'MIS Warning Notice — Month Detail'
    _order = 'period_date'

    notice_id = fields.Many2one('mis.warning.notice', required=True, ondelete='cascade', index=True)
    period_date = fields.Date(string='Month', required=True)
    period_label = fields.Char(string='Period')
    monthly_ctc = fields.Float(string='Monthly CTC')
    min_ctc_obligation = fields.Float(string='Minimum Obligation')
    payments_collected = fields.Float(string='Payment Collected')
    shortfall = fields.Float(string='Shortfall')
    performance_status = fields.Char(string='Status')
    currency_id = fields.Many2one('res.currency', related='notice_id.currency_id', readonly=True)


class MisWarningNotice(models.Model):
    """One escalation case per employee per below-target streak.

    A case is created the month the counter reaches 2 and lives until an On
    Track month closes it, advancing from "Flagged for HR" to a draft Warning
    Notice on month 3.  A new streak after a reset opens a NEW case, so the
    history of past escalations is preserved."""
    _name = 'mis.warning.notice'
    _description = 'MIS Performance Warning Notice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_date desc, employee_name'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')

    # ── Who ──────────────────────────────────────────────────────────────
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True,
                                  readonly=True, index=True, ondelete='cascade')
    employee_name = fields.Char(string='Employee Name', readonly=True)
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    performance_team = fields.Char(string='Team', readonly=True)
    office_location = fields.Char(string='Office', readonly=True)
    job_title = fields.Char(string='Job Title', readonly=True)

    # ── When / how far ───────────────────────────────────────────────────
    period_date = fields.Date(string='Triggering Month', required=True, readonly=True,
                              help="The most recent below-target month evaluated for this case.")
    period_label = fields.Char(string='Month', readonly=True)
    consecutive_months = fields.Integer(string='Consecutive Months Below Minimum', readonly=True,
                                        tracking=True)
    streak_start_label = fields.Char(string='Streak Started', readonly=True)

    stage = fields.Selection([
        ('flag', 'Month 2 — HR Flag'),
        ('notice', 'Month 3+ — Warning Notice'),
    ], string='Escalation Stage', readonly=True, tracking=True)

    state = fields.Selection([
        ('flagged', 'Flagged for HR'),
        ('draft', 'Draft Notice'),
        ('issued', 'Issued'),
        ('closed', 'Closed — Minimum Met'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='flagged', readonly=True, tracking=True, index=True)

    # ── Figures for the triggering month ─────────────────────────────────
    monthly_ctc = fields.Float(string='Monthly CTC', readonly=True)
    min_ctc_obligation = fields.Float(string='Minimum Obligation', readonly=True)
    payments_collected = fields.Float(string='Payment Collected', readonly=True)
    shortfall = fields.Float(string='Shortfall', readonly=True)
    total_shortfall = fields.Float(string='Cumulative Shortfall', compute='_compute_total_shortfall',
                                   store=True)
    currency_id = fields.Many2one('res.currency', string='Currency', readonly=True,
                                  default=lambda self: self._default_currency())

    month_ids = fields.One2many('mis.warning.notice.month', 'notice_id',
                                string='Below-Target Months', readonly=True)

    # ── Document ─────────────────────────────────────────────────────────
    notice_body = fields.Html(
        string='Draft Warning Notice',
        sanitize=False,
        help="Auto-generated draft for HR to review and edit before issuing. "
             "Regenerate with the button to discard edits and rebuild from current data.")

    flagged_date = fields.Date(string='Flagged On', readonly=True)
    notice_date = fields.Date(string='Draft Generated On', readonly=True)
    issued_date = fields.Date(string='Issued On', readonly=True)
    issued_by_id = fields.Many2one('res.users', string='Issued By', readonly=True)
    closed_date = fields.Date(string='Closed On', readonly=True)
    closed_period_label = fields.Char(string='Met Minimum In', readonly=True)
    hr_notified = fields.Boolean(string='HR Notified', readonly=True)

    company_id = fields.Many2one('res.company', string='Company', readonly=True,
                                 default=lambda self: self.env.company)

    # ─────────────────────────────────────────────────────────────────────
    # Defaults / computes
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _default_currency(self):
        """The performance view reports every figure in AED regardless of the
        employee's payroll currency, so the notice does the same."""
        aed = self.env['res.currency'].search([('name', '=', 'AED')], limit=1)
        return aed or self.env.company.currency_id

    @api.depends('month_ids.shortfall')
    def _compute_total_shortfall(self):
        for rec in self:
            rec.total_shortfall = sum(rec.month_ids.mapped('shortfall'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'mis.warning.notice') or '/'
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────────
    # Cron entry points
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _cron_run_escalation(self):
        """Runs monthly; evaluates the month that just closed (a run on
        1 Oct evaluates September)."""
        today = fields.Date.context_today(self)
        period_date = today.replace(day=1) - relativedelta(months=1)
        return self._run_escalation(period_date)

    # ─────────────────────────────────────────────────────────────────────
    # The escalation engine
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _counter_start(self):
        """First month the counter is allowed to count from, or None for the
        full history available in the performance view."""
        raw = (self.env['ir.config_parameter'].sudo()
               .get_param(COUNTER_START_PARAM) or '').strip()
        if not raw:
            return None
        try:
            return fields.Date.to_date(raw).replace(day=1)
        except (ValueError, TypeError):
            _logger.warning("%s is not a valid date (%r); ignoring the floor.",
                            COUNTER_START_PARAM, raw)
            return None

    @api.model
    def _effective_counter(self, raw_counter, period_date):
        """Cap the view's streak at the months elapsed since the counter start
        floor, so a policy that went live this month cannot retroactively
        warn someone for months the system never measured."""
        floor = self._counter_start()
        if not floor:
            return raw_counter
        months_available = ((period_date.year * 12 + period_date.month)
                            - (floor.year * 12 + floor.month) + 1)
        return max(0, min(raw_counter, months_available))

    @api.model
    def _read_performance_rows(self, period_date):
        """Every performance row up to and including `period_date` — the
        triggering month plus the history the streak table is built from."""
        lines = self.env['mis.performance.line'].sudo().search(
            [('period_date', '<=', period_date)], order='employee_id, period_date')
        return [{
            'employee_id': l.employee_id.id,
            'employee_name': l.employee_name,
            'user_id': l.user_id.id,
            'department_id': l.department_id.id,
            'performance_team': l.performance_team,
            'office_location': l.office_location,
            'period_date': l.period_date,
            'period_label': l.period_label,
            'monthly_ctc': l.monthly_ctc,
            'min_ctc_obligation': l.min_ctc_obligation,
            'payments_collected_amount': l.payments_collected_amount,
            'performance_status': l.performance_status,
            'consecutive_below_target': l.consecutive_below_target,
        } for l in lines if l.employee_id]

    @api.model
    def _run_escalation(self, period_date, rows=None, employee_ids=None):
        """Evaluate `period_date` for every employee under the framework and
        advance, open or close their escalation case.

        `rows` lets a caller (and the test suite) inject performance rows
        instead of reading ``mis.performance.line``; it must contain the
        history as well as the target month, in the shape produced by
        :meth:`_read_performance_rows`.

        `employee_ids` narrows the run to specific employees — how HR re-runs
        the counter for one person without touching everybody else's cases.

        Returns a dict summarising what the run did.
        """
        period_date = fields.Date.to_date(period_date).replace(day=1)
        if rows is None:
            rows = self._read_performance_rows(period_date)

        history = {}
        for row in rows:
            if employee_ids is not None and row['employee_id'] not in employee_ids:
                continue
            row_period = fields.Date.to_date(row['period_date'])
            if row_period <= period_date:
                history.setdefault(row['employee_id'], []).append(dict(row, period_date=row_period))
        for emp_rows in history.values():
            emp_rows.sort(key=lambda r: r['period_date'])

        summary = {'period': period_date, 'flagged': 0, 'drafted': 0,
                   'closed': 0, 'updated': 0, 'skipped_no_row': 0}

        case_domain = [('state', 'in', OPEN_STATES)]
        if employee_ids is not None:
            case_domain.append(('employee_id', 'in', list(employee_ids)))
        open_cases = self.sudo().search(case_domain)
        cases_by_employee = {c.employee_id.id: c for c in open_cases}

        for employee_id, emp_rows in history.items():
            target = next((r for r in emp_rows if r['period_date'] == period_date), None)
            if not target:
                summary['skipped_no_row'] += 1
                continue

            case = cases_by_employee.get(employee_id)
            on_track = target.get('performance_status') in ON_TRACK_STATUSES
            counter = 0 if on_track else self._effective_counter(
                target.get('consecutive_below_target') or 0, period_date)

            if counter == 0:
                if case:
                    case._close_as_met(target)
                    summary['closed'] += 1
                continue

            if counter >= NOTICE_THRESHOLD:
                case, outcome = self._open_or_advance(case, target, emp_rows, counter, 'notice')
                summary[outcome] += 1
            elif counter >= FLAG_THRESHOLD:
                case, outcome = self._open_or_advance(case, target, emp_rows, counter, 'flag')
                summary[outcome] += 1
            # counter == 1 → verbal stage, deliberately no system record.

            cases_by_employee[employee_id] = case

        _logger.info(
            "MIS Warning Notice counter for %s: %s flagged, %s drafted, %s closed, %s refreshed.",
            period_date.strftime('%b %Y'), summary['flagged'], summary['drafted'],
            summary['closed'], summary['updated'])
        return summary

    @api.model
    def _open_or_advance(self, case, target, emp_rows, counter, stage):
        """Create the case if this is the first escalating month, then move it
        to `stage` if it is not there yet.  An already-issued notice is never
        rewritten — only its figures are refreshed.

        Returns ``(case, outcome)`` where outcome is one of ``flagged``,
        ``drafted`` or ``updated`` — recordsets use ``__slots__``, so the
        outcome cannot be stashed on the record itself."""
        streak_rows = self._streak_rows(emp_rows, counter)
        vals = {
            'employee_name': target.get('employee_name'),
            'user_id': target.get('user_id') or False,
            'department_id': target.get('department_id') or False,
            'performance_team': (target.get('performance_team') or '').title() or False,
            'office_location': target.get('office_location'),
            'period_date': target['period_date'],
            'period_label': target.get('period_label'),
            'consecutive_months': counter,
            'streak_start_label': streak_rows[0].get('period_label') if streak_rows else False,
            'monthly_ctc': target.get('monthly_ctc') or 0.0,
            'min_ctc_obligation': target.get('min_ctc_obligation') or 0.0,
            'payments_collected': target.get('payments_collected_amount') or 0.0,
            'shortfall': max(0.0, (target.get('min_ctc_obligation') or 0.0)
                             - (target.get('payments_collected_amount') or 0.0)),
        }

        if not case:
            employee = self.env['hr.employee'].sudo().browse(target['employee_id'])
            case = self.sudo().create(dict(
                vals,
                employee_id=target['employee_id'],
                job_title=employee.job_title or employee.job_id.name or False,
                state='flagged',
                stage='flag',
                flagged_date=fields.Date.context_today(self),
            ))
        else:
            case.sudo().write(vals)

        case.sudo()._rebuild_month_lines(streak_rows)

        outcome = 'updated'
        if case.stage != 'notice' and stage == 'notice':
            case._advance_to_notice()
            outcome = 'drafted'
        elif not case.hr_notified and stage == 'flag':
            case._advance_to_flag()
            outcome = 'flagged'

        return case, outcome

    @api.model
    def _streak_rows(self, emp_rows, counter):
        """The last `counter` rows of the employee's history — the months that
        make up the current below-target streak."""
        return emp_rows[-counter:] if counter else []

    # ─────────────────────────────────────────────────────────────────────
    # Stage transitions
    # ─────────────────────────────────────────────────────────────────────
    def _advance_to_flag(self):
        """Month 2: raise the in-system flag for HR."""
        self.ensure_one()
        self.sudo().write({
            'stage': 'flag',
            'state': 'flagged',
            'flagged_date': self.flagged_date or fields.Date.context_today(self),
        })
        self._notify_hr(
            _("Performance flag — %(employee)s has missed the monthly minimum "
              "for %(months)s consecutive months (%(period)s).",
              employee=self.employee_name or '', months=self.consecutive_months,
              period=self.period_label or ''),
            summary=_("Performance flag: %s", self.employee_name or ''),
        )
        self.sudo().hr_notified = True

    def _advance_to_notice(self):
        """Month 3: generate the draft Warning Notice for HR to review."""
        self.ensure_one()
        self.sudo().write({
            'stage': 'notice',
            'state': 'draft',
            'notice_date': fields.Date.context_today(self),
            'notice_body': self._build_notice_body(),
        })
        self._notify_hr(
            _("Draft Warning Notice generated for %(employee)s — "
              "%(months)s consecutive months below the monthly minimum "
              "(latest: %(period)s). Review and issue.",
              employee=self.employee_name or '', months=self.consecutive_months,
              period=self.period_label or ''),
            summary=_("Review Warning Notice: %s", self.employee_name or ''),
        )
        self.sudo().hr_notified = True

    def _close_as_met(self, target):
        """An On Track month resets the counter and closes the case."""
        self.ensure_one()
        self.sudo().write({
            'state': 'closed',
            'closed_date': fields.Date.context_today(self),
            'closed_period_label': target.get('period_label'),
        })
        self.activity_unlink(['mail.mail_activity_data_todo'])
        self.message_post(body=_(
            "Counter reset — %(employee)s met the monthly minimum in %(period)s "
            "(collected %(collected)s against a minimum of %(minimum)s). "
            "Escalation closed.",
            employee=self.employee_name or '',
            period=target.get('period_label') or '',
            collected='%.2f' % (target.get('payments_collected_amount') or 0.0),
            minimum='%.2f' % (target.get('min_ctc_obligation') or 0.0)))

    def _rebuild_month_lines(self, streak_rows):
        self.ensure_one()
        self.month_ids.unlink()
        self.month_ids = [(0, 0, {
            'period_date': r['period_date'],
            'period_label': r.get('period_label'),
            'monthly_ctc': r.get('monthly_ctc') or 0.0,
            'min_ctc_obligation': r.get('min_ctc_obligation') or 0.0,
            'payments_collected': r.get('payments_collected_amount') or 0.0,
            'shortfall': max(0.0, (r.get('min_ctc_obligation') or 0.0)
                             - (r.get('payments_collected_amount') or 0.0)),
            'performance_status': r.get('performance_status'),
        }) for r in streak_rows]

    # ─────────────────────────────────────────────────────────────────────
    # HR notification — an in-system activity, not just an email.
    # ─────────────────────────────────────────────────────────────────────
    def _hr_users(self):
        users = self.env['res.users']
        for xmlid in ('mis_report_kgrn.group_mis_hr', 'mis_report_kgrn.group_mis_admin'):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.users
        return users.filtered(lambda u: u.active)

    def _notify_hr(self, body, summary):
        """Post to the case chatter and put a To-Do on every HR user.

        Deliberately an activity rather than an email: outgoing mail on this
        instance is unreliable, and the policy asks for a flag *in the
        system*.  The mail template (if configured) rides along on the
        chatter post for anyone following the record."""
        self.ensure_one()
        self.message_post(body=body, subtype_xmlid='mail.mt_note')
        hr_users = self._hr_users()
        if not hr_users:
            _logger.warning(
                "MIS Warning Notice %s: no MIS HR / MIS Admin users to flag.", self.name)
            return
        deadline = fields.Date.context_today(self) + relativedelta(days=7)
        for user in hr_users:
            self.sudo().activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=deadline,
                summary=summary,
                note=body,
                user_id=user.id,
            )

    # ─────────────────────────────────────────────────────────────────────
    # Notice body
    # ─────────────────────────────────────────────────────────────────────
    def _fmt(self, amount):
        symbol = self.currency_id.symbol or 'AED'
        return '%s %s' % (symbol, '{:,.2f}'.format(amount or 0.0))

    def _build_notice_body(self):
        """The draft HR reviews. Plain inline-styled HTML so it survives both
        the Odoo HTML editor and wkhtmltopdf."""
        self.ensure_one()
        rows = ''.join(
            '<tr>'
            '<td style="border:1px solid #ccc;padding:6px;">%s</td>'
            '<td style="border:1px solid #ccc;padding:6px;text-align:right;">%s</td>'
            '<td style="border:1px solid #ccc;padding:6px;text-align:right;">%s</td>'
            '<td style="border:1px solid #ccc;padding:6px;text-align:right;color:#9c0006;">%s</td>'
            '<td style="border:1px solid #ccc;padding:6px;">%s</td>'
            '</tr>' % (
                m.period_label or '',
                self._fmt(m.min_ctc_obligation),
                self._fmt(m.payments_collected),
                self._fmt(m.shortfall),
                m.performance_status or '',
            ) for m in self.month_ids)

        return """
<div style="font-family:Arial,Helvetica,sans-serif;font-size:13px;color:#333;line-height:1.6;">
  <p><strong>To:</strong> {employee}{job}<br/>
     <strong>Department:</strong> {department}<br/>
     <strong>Reference:</strong> {reference}<br/>
     <strong>Subject:</strong> Warning Notice — Failure to Meet Minimum Monthly Obligation</p>

  <p>Dear {employee},</p>

  <p>This notice is issued under the KGRN Performance Management Policy
     (HR-PMS-001). Your recorded Payment Collected has remained below the
     minimum monthly obligation applicable to your role for
     <strong>{months} consecutive months</strong>, from {streak_start} to
     {period}.</p>

  <p>Your minimum monthly obligation is calculated as Monthly CTC
     ({ctc}) &#215; the multiplier for your office location ({office}),
     giving <strong>{minimum}</strong> per month.</p>

  <table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:12px;">
    <thead>
      <tr style="background:#714B67;color:#fff;">
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">Month</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">Minimum Obligation</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">Payment Collected</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:right;">Shortfall</th>
        <th style="border:1px solid #ccc;padding:6px;text-align:left;">Status</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
    <tfoot>
      <tr style="background:#f3f0f7;font-weight:bold;">
        <td style="border:1px solid #ccc;padding:6px;">Cumulative shortfall</td>
        <td style="border:1px solid #ccc;padding:6px;"></td>
        <td style="border:1px solid #ccc;padding:6px;"></td>
        <td style="border:1px solid #ccc;padding:6px;text-align:right;color:#9c0006;">{total}</td>
        <td style="border:1px solid #ccc;padding:6px;"></td>
      </tr>
    </tfoot>
  </table>

  <p>You are required to bring your performance up to the minimum obligation
     in the current month. A Performance Improvement Plan (PIP) will be agreed
     with your reporting manager, and continued shortfall may lead to further
     action under the policy.</p>

  <p>Should you consider that the figures above are incorrect — for example
     work delivered but not yet invoiced or collected — please raise this with
     HR within seven (7) days of receiving this notice.</p>

  <p>Regards,<br/>Human Resources<br/>KGRN Chartered Accountants</p>
</div>""".format(
            employee=self.employee_name or '',
            job=(' — %s' % self.job_title) if self.job_title else '',
            department=self.department_id.name or '—',
            reference=self.name or '',
            months=self.consecutive_months,
            streak_start=self.streak_start_label or self.period_label or '',
            period=self.period_label or '',
            ctc=self._fmt(self.monthly_ctc),
            office=self.office_location or '—',
            minimum=self._fmt(self.min_ctc_obligation),
            rows=rows,
            total=self._fmt(self.total_shortfall),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Buttons
    # ─────────────────────────────────────────────────────────────────────
    def action_regenerate_notice(self):
        """Discard HR's edits and rebuild the draft from current data."""
        for rec in self:
            if rec.state not in ('flagged', 'draft'):
                raise UserError(_("Only a flagged or draft notice can be regenerated."))
            rec.sudo().write({
                'stage': 'notice',
                'state': 'draft',
                'notice_date': rec.notice_date or fields.Date.context_today(rec),
                'notice_body': rec._build_notice_body(),
            })
        return True

    def action_issue(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only a draft Warning Notice can be issued."))
            if not rec.notice_body:
                raise UserError(_("Generate the notice body before issuing."))
            rec.sudo().write({
                'state': 'issued',
                'issued_date': fields.Date.context_today(rec),
                'issued_by_id': rec.env.user.id,
            })
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            rec.message_post(body=_("Warning Notice issued by %s.", rec.env.user.name))
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'closed':
                raise UserError(_("A closed case cannot be cancelled."))
            rec.sudo().write({'state': 'cancelled'})
            rec.activity_unlink(['mail.mail_activity_data_todo'])
            rec.message_post(body=_("Escalation cancelled by %s.", rec.env.user.name))
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('issued', 'cancelled'):
                raise UserError(_("Only an issued or cancelled notice can be reset to draft."))
            rec.sudo().write({'state': 'draft', 'issued_date': False, 'issued_by_id': False})
        return True

    def action_view_performance(self):
        """Open the employee's performance rows behind this escalation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Performance — %s', self.employee_name or ''),
            'res_model': 'mis.performance.line',
            'view_mode': 'list',
            'domain': [('employee_id', '=', self.employee_id.id)],
            'target': 'current',
        }

    @api.model
    def action_run_escalation_now(self, employee_ids=None):
        """Menu/server-action entry point: re-run the counter for the month
        that has just closed, without waiting for the cron."""
        today = fields.Date.context_today(self)
        summary = self._run_escalation(
            today.replace(day=1) - relativedelta(months=1), employee_ids=employee_ids)
        message = _(
            "Escalation check for %(period)s complete — %(flagged)s newly flagged, "
            "%(drafted)s draft notice(s) generated, %(closed)s closed on reset, "
            "%(updated)s refreshed.",
            period=summary['period'].strftime('%b %Y'), flagged=summary['flagged'],
            drafted=summary['drafted'], closed=summary['closed'], updated=summary['updated'])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Warning Notice Counter'), 'message': message,
                       'type': 'success', 'sticky': False,
                       'next': {'type': 'ir.actions.act_window_close'}},
        }
