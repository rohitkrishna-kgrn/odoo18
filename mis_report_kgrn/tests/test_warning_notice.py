"""Tests for the Warning Notice counter (HR-PMS-001 §Escalation).

The escalation engine reads ``mis.performance.line``, a SQL view built from
posted invoices, reconciliations, timesheets and contracts — far too much
fixture to stand up per test.  ``_run_escalation`` therefore accepts a ``rows``
argument in exactly the shape ``_read_performance_rows`` produces, and these
tests feed it a synthetic history.  ``_history`` below reproduces the view's
own Status and streak rules (see the SQL in ``mis_performance.py``), so what is
under test is the escalation state machine, not a re-implementation of it.

The behaviours worth guarding:
  * month 1 leaves no trace, month 2 flags HR, month 3 drafts the notice;
  * a single On Track month closes the case and the counter starts over;
  * an already-issued notice is never silently rewritten by a later run;
  * re-running the same month twice does not duplicate cases or flags;
  * the counter-start floor stops a brand-new policy from retroactively
    warning staff for months the system never measured.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError

CTC = 10000.0        # monthly CTC
MINIMUM = 30000.0    # UAE minimum = CTC x 3


@tagged('post_install', '-at_install')
class TestWarningNoticeCounter(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Notice = cls.env['mis.warning.notice']
        cls.employee = cls.env['hr.employee'].create({
            'name': 'WN Test Auditor',
            'mis_performance_applicable': True,
            'mis_office_location': 'uae',
            'mis_performance_team': 'audit',
        })
        # No floor by default: each test sets the one it needs.
        cls.env['ir.config_parameter'].sudo().set_param(
            'mis_report_kgrn.escalation_counter_start', '')

    # ── fixtures ─────────────────────────────────────────────────────────
    def _history(self, collections, start='2026-01-01', employee=None, ctc=CTC):
        """Build performance rows for consecutive months from `start`.

        `collections` is the Payment Collected for each month. Status and the
        consecutive-below-target streak follow the same rules as the SQL view:
        below CTC is 'Below Minimum', below the obligation is 'At Risk', at or
        above it is 'On Track', and an On Track (or 'N/A') month resets the
        streak to zero.
        """
        employee = employee or self.employee
        minimum = ctc * 3
        period = fields.Date.to_date(start)
        rows, streak = [], 0
        for collected in collections:
            if not ctc:
                status = 'N/A'
            elif collected < ctc:
                status = 'Below Minimum'
            elif collected < minimum:
                status = 'At Risk'
            else:
                status = 'On Track'
            streak = 0 if status in ('On Track', 'N/A') else streak + 1
            rows.append({
                'employee_id': employee.id,
                'employee_name': employee.name,
                'user_id': False,
                'department_id': False,
                'performance_team': 'audit',
                'office_location': 'UAE',
                'period_date': period,
                'period_label': period.strftime('%b %Y'),
                'monthly_ctc': ctc,
                'min_ctc_obligation': minimum,
                'payments_collected_amount': collected,
                'performance_status': status,
                'consecutive_below_target': streak,
            })
            period += relativedelta(months=1)
        return rows

    def _run(self, rows, months_in=None, employee=None):
        """Run the engine for the last month of `rows` (or the Nth month)."""
        target = rows[(months_in - 1) if months_in else -1]['period_date']
        self.Notice._run_escalation(target, rows=rows)
        return self._case(employee)

    def _case(self, employee=None):
        return self.Notice.search(
            [('employee_id', '=', (employee or self.employee).id)],
            order='id desc', limit=1)

    def _cases(self, employee=None):
        return self.Notice.search(
            [('employee_id', '=', (employee or self.employee).id)], order='id')

    # ── month 1: nothing happens ─────────────────────────────────────────
    def test_month1_creates_no_record(self):
        """The first below-target month is a verbal flag, handled off-system."""
        rows = self._history([0.0])
        case = self._run(rows)
        self.assertFalse(case, "Month 1 must not create an escalation record")

    # ── month 2: auto-flag for HR ────────────────────────────────────────
    def test_month2_flags_for_hr(self):
        rows = self._history([0.0, 0.0])
        case = self._run(rows)
        self.assertTrue(case, "Month 2 must create an escalation record")
        self.assertEqual(case.state, 'flagged')
        self.assertEqual(case.stage, 'flag')
        self.assertEqual(case.consecutive_months, 2)
        self.assertTrue(case.hr_notified)
        self.assertTrue(case.activity_ids, "HR must get an in-system To-Do")
        self.assertFalse(case.notice_body, "No notice document until month 3")
        self.assertEqual(len(case.month_ids), 2)
        self.assertEqual(case.name[:3], 'WN/')

    def test_month2_flag_visible_on_employee(self):
        """HR should see the flag from the employee record too."""
        self._run(self._history([0.0, 0.0]))
        self.employee.invalidate_recordset()
        self.assertTrue(self.employee.mis_hr_flagged)
        self.assertEqual(self.employee.mis_consecutive_below_target, 2)
        self.assertEqual(self.employee.mis_warning_notice_count, 1)
        found = self.env['hr.employee'].search([('mis_hr_flagged', '=', True)])
        self.assertIn(self.employee, found, "The flag must be searchable")

    # ── month 3: draft Warning Notice ────────────────────────────────────
    def test_month3_generates_draft_notice(self):
        rows = self._history([0.0, 0.0, 5000.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        self.assertEqual(len(self._cases()), 1, "The streak must stay one case")
        self.assertEqual(case.state, 'draft')
        self.assertEqual(case.stage, 'notice')
        self.assertEqual(case.consecutive_months, 3)
        self.assertTrue(case.notice_body, "Month 3 must generate the draft document")
        self.assertIn('WN Test Auditor', case.notice_body)
        self.assertIn('3 consecutive months', case.notice_body)
        self.assertEqual(len(case.month_ids), 3)
        # Shortfall accumulates across the streak: 30000 + 30000 + 25000.
        self.assertAlmostEqual(case.total_shortfall, 85000.0, places=2)
        self.assertAlmostEqual(case.shortfall, 25000.0, places=2)

    def test_month3_draft_is_not_auto_issued(self):
        """HR reviews and issues; the system never issues by itself."""
        rows = self._history([0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        self.assertEqual(case.state, 'draft')
        self.assertFalse(case.issued_date)
        self.assertFalse(case.issued_by_id)

    def test_fourth_month_does_not_open_second_case(self):
        rows = self._history([0.0, 0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        self._run(rows, months_in=3)
        case = self._run(rows)
        self.assertEqual(len(self._cases()), 1)
        self.assertEqual(case.consecutive_months, 4)
        self.assertEqual(len(case.month_ids), 4)

    # ── reset ────────────────────────────────────────────────────────────
    def test_counter_resets_when_minimum_met(self):
        rows = self._history([0.0, 0.0, 0.0, MINIMUM])
        self._run(rows, months_in=2)
        self._run(rows, months_in=3)
        case = self._run(rows)
        self.assertEqual(case.state, 'closed')
        self.assertEqual(case.closed_period_label, 'Apr 2026')
        self.assertTrue(case.closed_date)
        self.assertFalse(case.activity_ids, "Closing must clear HR's To-Do")

    def test_new_streak_after_reset_opens_a_new_case(self):
        """History is preserved: the reset case stays closed and a fresh one
        opens rather than the old one being reused."""
        rows = self._history([0.0, 0.0, MINIMUM, 0.0, 0.0])
        for month in (2, 3, 4, 5):
            self._run(rows, months_in=month)
        cases = self._cases()
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].state, 'closed')
        self.assertEqual(cases[1].state, 'flagged')
        self.assertEqual(cases[1].consecutive_months, 2)

    def test_on_track_month_alone_never_escalates(self):
        rows = self._history([MINIMUM, MINIMUM, MINIMUM])
        for month in (1, 2, 3):
            self._run(rows, months_in=month)
        self.assertFalse(self._cases())

    def test_no_ctc_on_record_never_escalates(self):
        """'N/A' (no open contract / zero CTC) must not accrue an escalation
        off a zero threshold."""
        rows = self._history([0.0, 0.0, 0.0], ctc=0.0)
        for month in (1, 2, 3):
            self._run(rows, months_in=month)
        self.assertFalse(self._cases())

    # ── idempotence ──────────────────────────────────────────────────────
    def test_rerunning_the_same_month_is_idempotent(self):
        rows = self._history([0.0, 0.0])
        case = self._run(rows)
        activities_after_first = len(case.activity_ids)
        self._run(rows)
        self.assertEqual(len(self._cases()), 1, "A re-run must not duplicate the case")
        self.assertEqual(len(case.activity_ids), activities_after_first,
                         "A re-run must not re-flag HR")

    # ── issuing ──────────────────────────────────────────────────────────
    def test_issue_notice(self):
        rows = self._history([0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        case.action_issue()
        self.assertEqual(case.state, 'issued')
        self.assertEqual(case.issued_by_id, self.env.user)
        self.assertTrue(case.issued_date)
        self.assertFalse(case.activity_ids, "Issuing must clear HR's To-Do")

    def test_cannot_issue_before_month3(self):
        case = self._run(self._history([0.0, 0.0]))
        self.assertEqual(case.state, 'flagged')
        with self.assertRaises(UserError):
            case.action_issue()

    def test_issued_notice_is_not_rewritten_by_a_later_run(self):
        """A fourth below-target month refreshes the figures but must not
        quietly revert an issued notice to draft."""
        rows = self._history([0.0, 0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows, months_in=3)
        case.action_issue()
        body_when_issued = case.notice_body
        case = self._run(rows)
        self.assertEqual(case.state, 'issued')
        self.assertEqual(case.notice_body, body_when_issued)
        self.assertEqual(case.consecutive_months, 4, "Figures still refresh")

    def test_regenerate_rebuilds_the_draft(self):
        rows = self._history([0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        case.notice_body = '<p>edited by HR</p>'
        case.action_regenerate_notice()
        self.assertNotIn('edited by HR', case.notice_body)
        self.assertIn('WN Test Auditor', case.notice_body)

    def test_cancel_and_reset(self):
        rows = self._history([0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        case.action_cancel()
        self.assertEqual(case.state, 'cancelled')
        self.assertFalse(case.activity_ids)
        case.action_reset_to_draft()
        self.assertEqual(case.state, 'draft')

    # ── counter-start floor ──────────────────────────────────────────────
    def test_counter_start_floor_caps_the_streak(self):
        """With the floor at the third month, a 3-month history can only be
        month 1 of the counter — no flag, no notice."""
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_report_kgrn.escalation_counter_start', '2026-03-01')
        rows = self._history([0.0, 0.0, 0.0])
        case = self._run(rows)
        self.assertFalse(case, "Months before the floor must not count")

    def test_counter_start_floor_allows_the_streak_to_build(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_report_kgrn.escalation_counter_start', '2026-03-01')
        rows = self._history([0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertFalse(self._run(rows, months_in=3), 'Mar = counter month 1')
        case = self._run(rows, months_in=4)
        self.assertEqual(case.state, 'flagged', 'Apr = counter month 2')
        self.assertEqual(case.consecutive_months, 2)
        case = self._run(rows, months_in=5)
        self.assertEqual(case.state, 'draft', 'May = counter month 3')
        self.assertEqual(case.consecutive_months, 3)

    def test_invalid_floor_is_ignored(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_report_kgrn.escalation_counter_start', 'not-a-date')
        case = self._run(self._history([0.0, 0.0]))
        self.assertEqual(case.state, 'flagged')

    # ── independence between employees ───────────────────────────────────
    def test_employees_are_scored_independently(self):
        other = self.env['hr.employee'].create({
            'name': 'WN Test Performer',
            'mis_performance_applicable': True,
            'mis_office_location': 'uae',
        })
        rows = (self._history([0.0, 0.0, 0.0])
                + self._history([MINIMUM, MINIMUM, MINIMUM], employee=other))
        for month in (1, 2, 3):
            self.Notice._run_escalation(
                fields.Date.to_date('2026-01-01') + relativedelta(months=month - 1),
                rows=rows)
        self.assertEqual(self._case().state, 'draft')
        self.assertFalse(self._cases(employee=other))

    # ── the document ─────────────────────────────────────────────────────
    def test_notice_pdf_renders(self):
        rows = self._history([0.0, 0.0, 0.0])
        self._run(rows, months_in=2)
        case = self._run(rows)
        html = self.env['ir.actions.report']._render_qweb_html(
            'mis_report_kgrn.report_mis_warning_notice_doc', case.ids)[0]
        self.assertIn(b'Warning Notice', html)
        self.assertIn(b'WN Test Auditor', html)
        self.assertIn(b'DRAFT', html, 'An unissued notice must be watermarked DRAFT')

    def test_cron_targets_the_month_just_closed(self):
        """The cron must evaluate the previous month, not the current one.

        This is the one test that runs against the real ``mis.performance.line``
        view rather than synthetic rows, so it also proves the column names
        ``_read_performance_rows`` reads still exist. The floor is pushed into
        the future so the run is a cheap no-op on live data instead of drafting
        a notice for every employee inside the test transaction.
        """
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_report_kgrn.escalation_counter_start', '2099-01-01')
        summary = self.Notice._cron_run_escalation()
        expected = (fields.Date.context_today(self.Notice).replace(day=1)
                    - relativedelta(months=1))
        self.assertEqual(summary['period'], expected)
        self.assertEqual(summary['flagged'], 0)
        self.assertEqual(summary['drafted'], 0)

    # ── single-employee re-run ───────────────────────────────────────────
    def test_run_can_be_scoped_to_one_employee(self):
        """HR must be able to re-run the counter for one person without
        opening or closing anybody else's case."""
        other = self.env['hr.employee'].create({
            'name': 'WN Test Bystander',
            'mis_performance_applicable': True,
            'mis_office_location': 'uae',
        })
        rows = (self._history([0.0, 0.0])
                + self._history([0.0, 0.0], employee=other))
        self.Notice._run_escalation(
            fields.Date.to_date('2026-02-01'), rows=rows,
            employee_ids=[self.employee.id])
        self.assertTrue(self._case(), "The targeted employee is escalated")
        self.assertFalse(self._cases(employee=other),
                         "A scoped run must leave other employees untouched")
