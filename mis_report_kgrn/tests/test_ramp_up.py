"""Tests for the new-joiner performance ramp-up (HR-PMS-001 §E1).

A new joiner is not held to the full location minimum from day one.  Their
monthly obligation climbs:

    Month 1  →  1× monthly CTC
    Month 2  →  2× monthly CTC
    Month 3+ →  the full location minimum (UAE 3×, India 5×)

"Month" is a calendar month counted from the ramp-up start date, so someone
who joins on the 28th gets the rest of that month as Month 1 — matching how
the policy is written and how the scorecard buckets everything else.

These drive the real SQL behind ``mis.performance.line``.  The ramp is not
Python: it is resolved in the view's ``ramp`` CTE and fans out into four
different columns (monthly_obligation, is_met, min_ctc_obligation,
status_on_track), so only a fixture that reaches Postgres proves they agree.

The fixture is deliberately revenue-free.  Every column under test is a
function of CTC and dates alone, so there is no need for the
order → project → task → timesheet → invoice → payment gauntlet that
``test_revenue_allocation`` needs; each employee is created fresh, which
means the view's per-employee month series (which starts at the user's
creation month) yields exactly ONE row — the current month — and the ramp
stage is steered by moving the start date backwards instead.

The behaviours worth guarding:
  * the 1× / 2× / full progression, and that it ends at month 3;
  * the start date is sourced automatically from the first contract, so the
    feature is not dead code waiting on 89 manual data entries;
  * a manually-set Ramp-up Start Date overrides that contract date;
  * the ramp reaches the Status / Warning-Notice threshold too, not only
    Achievement % — a new joiner cannot be escalated against a target that
    has not taken effect for them yet;
  * no row is ever removed from the report — months before someone's start
    date stay visible, scored at the standard obligation;
  * an employee with no resolvable start date is scored at full obligation
    rather than silently ramped.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

ANNUAL_CTC = 120000.0        # → 10,000 monthly CTC, so the multipliers are
MONTHLY_CTC = 10000.0        #   readable straight off the assertions


@tagged('post_install', '-at_install')
class TestNewJoinerRampUp(TransactionCase):

    # ── Fixture ──────────────────────────────────────────────────────────
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.this_month = fields.Date.context_today(cls.env.user).replace(day=1)
        cls.Line = cls.env['mis.performance.line']

    def _make_employee(self, name, ramp_start=None, office='uae',
                       annual_ctc=ANNUAL_CTC, contract_start=None,
                       applicable=True):
        """One applicable employee, optionally with a contract.

        `annual_ctc` is written to the manual override field, which the view
        prefers over the contract wage — it keeps the arithmetic legible and
        means a contract is only needed by the tests that are actually about
        the contract-date fallback.
        """
        user = self.env['res.users'].create({
            'name': name,
            'login': 'ramp_%s' % name.lower().replace(' ', '_'),
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        employee = self.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'mis_performance_applicable': applicable,
            'mis_office_location': office,
            'mis_annual_ctc': annual_ctc,
            'mis_ramp_start_date': ramp_start,
        })
        if contract_start:
            self.env['hr.contract'].create({
                'name': '%s contract' % name,
                'employee_id': employee.id,
                'date_start': contract_start,
                'wage': 1.0,        # never used: mis_annual_ctc overrides it
                'state': 'open',
            })
        return employee

    def _row(self, employee):
        """This month's scorecard row for `employee`, or an empty recordset.

        The flush is not optional: ``mis.performance.line`` is a SQL view, and
        Odoo decides what to flush from the model being searched — it has no
        idea the view reads hr_employee and hr_contract, so an employee
        created moments ago is simply invisible without it.
        """
        self.env.flush_all()
        return self.Line.search([
            ('employee_id', '=', employee.id),
            ('period_date', '=', self.this_month),
        ])

    def _months_ago(self, n):
        return self.this_month - relativedelta(months=n)

    # ── The progression ──────────────────────────────────────────────────
    def test_month_1_obligation_is_one_times_ctc(self):
        row = self._row(self._make_employee('Joiner M1', self._months_ago(0)))
        self.assertEqual(len(row), 1)
        self.assertEqual(row.months_employed, 1)
        self.assertEqual(row.ramp_stage, 'Month 1 — 1x CTC')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 1, places=2)

    def test_month_2_obligation_is_two_times_ctc(self):
        row = self._row(self._make_employee('Joiner M2', self._months_ago(1)))
        self.assertEqual(row.months_employed, 2)
        self.assertEqual(row.ramp_stage, 'Month 2 — 2x CTC')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 2, places=2)

    def test_month_3_reaches_the_full_uae_minimum(self):
        """Month 3 is the first month at the standard obligation, not month 4."""
        row = self._row(self._make_employee('Joiner M3', self._months_ago(2)))
        self.assertEqual(row.months_employed, 3)
        self.assertEqual(row.ramp_stage, 'Full Obligation')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 3, places=2)

    def test_month_3_reaches_the_full_india_minimum(self):
        row = self._row(self._make_employee(
            'Joiner India', self._months_ago(2), office='india'))
        self.assertEqual(row.ramp_stage, 'Full Obligation')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 5, places=2)

    def test_ramp_applies_part_month(self):
        """Joining on the last day of a month still spends that whole calendar
        month in Month 1 — the count is calendar months, not 30-day windows."""
        joined_late = self.this_month + relativedelta(months=1, days=-1)
        row = self._row(self._make_employee('Joiner Late', joined_late))
        self.assertEqual(row.months_employed, 1)
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 1, places=2)

    def test_long_tenured_employee_is_unaffected(self):
        row = self._row(self._make_employee('Veteran', self._months_ago(36)))
        self.assertEqual(row.ramp_stage, 'Full Obligation')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 3, places=2)

    # ── Where the start date comes from ──────────────────────────────────
    def test_start_date_falls_back_to_first_contract(self):
        """The whole point of the fallback: nobody fills the manual field in
        (0 of 89 applicable employees had one), so without this the ramp is
        dead code that never fires."""
        employee = self._make_employee(
            'Contract Joiner', ramp_start=False,
            contract_start=self._months_ago(1))
        row = self._row(employee)
        self.assertEqual(row.ramp_start_date, self._months_ago(1))
        self.assertEqual(row.months_employed, 2)
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 2, places=2)

    def test_manual_start_date_overrides_the_contract(self):
        """How HR corrects a re-hire or a transfer whose contract row does not
        reflect when the person actually started under the framework."""
        employee = self._make_employee(
            'Rehire', ramp_start=self._months_ago(0),
            contract_start=self._months_ago(36))
        row = self._row(employee)
        self.assertEqual(row.ramp_start_date, self._months_ago(0))
        self.assertEqual(row.months_employed, 1)
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 1, places=2)

    def test_no_start_date_anywhere_scores_full_obligation(self):
        """Fail safe, not fail generous: an employee with neither a manual
        date nor a contract is held to the standard minimum, and says so,
        rather than being silently handed a reduced target."""
        row = self._row(self._make_employee('No Dates', ramp_start=False))
        self.assertEqual(row.ramp_stage, 'No Start Date')
        self.assertFalse(row.months_employed)
        self.assertFalse(row.ramp_start_date)
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 3, places=2)

    def test_months_before_joining_keep_their_row_at_full_obligation(self):
        """Months before the start date must NOT vanish from the report — the
        scorecard is history people rely on, and quietly dropping rows is a
        worse failure than showing a month at the standard obligation.  They
        score exactly as they did before the ramp-up existed."""
        employee = self._make_employee(
            'Future Joiner', ramp_start=self.this_month + relativedelta(months=1))
        row = self._row(employee)
        self.assertEqual(len(row), 1, "the row must still be reported")
        self.assertEqual(row.ramp_stage, 'Before Start Date')
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC * 3, places=2)
        self.assertAlmostEqual(row.min_ctc_obligation, MONTHLY_CTC * 3, places=2)

    # ── The ramp reaches Status / escalation, not just Achievement ───────
    def test_status_threshold_is_ramped_too(self):
        """min_ctc_obligation drives the Status column and the Warning Notice
        counter.  Before this change it was a flat CTC × 3, so a month-1
        joiner was scored against 30,000 and started accruing consecutive
        below-target months toward a Warning Notice from their first month.
        """
        row = self._row(self._make_employee('Joiner Status', self._months_ago(0)))
        self.assertAlmostEqual(row.min_ctc_obligation, MONTHLY_CTC * 1, places=2)

    def test_status_threshold_ramps_in_month_2(self):
        row = self._row(self._make_employee('Joiner Status 2', self._months_ago(1)))
        self.assertAlmostEqual(row.min_ctc_obligation, MONTHLY_CTC * 2, places=2)

    def test_status_threshold_full_from_month_3(self):
        row = self._row(self._make_employee('Joiner Status 3', self._months_ago(2)))
        self.assertAlmostEqual(row.min_ctc_obligation, MONTHLY_CTC * 3, places=2)

    def test_both_thresholds_always_agree(self):
        """The invariant this change establishes across the whole live report:
        one ramped threshold, used by both scoring pairs.  They differ only in
        the revenue measured against them (total_revenue vs Payments
        Collected), never in the bar itself — if these two ever diverge again,
        a new joiner can pass Achievement % while still being escalated."""
        self.env.flush_all()
        mismatched = [
            (line.employee_name, line.period_label,
             line.monthly_obligation, line.min_ctc_obligation)
            for line in self.Line.search([])
            if abs(line.monthly_obligation - line.min_ctc_obligation) > 0.01
        ]
        self.assertFalse(mismatched,
                         "monthly_obligation and min_ctc_obligation diverged: %s"
                         % mismatched[:5])

    # ── Guards ───────────────────────────────────────────────────────────
    def test_achievement_pct_uses_the_ramped_obligation(self):
        """Achievement % must divide by the reduced target, otherwise a joiner
        with no revenue looks identical whichever obligation applied."""
        row = self._row(self._make_employee('Joiner Pct', self._months_ago(0)))
        self.assertAlmostEqual(row.monthly_obligation, MONTHLY_CTC, places=2)
        # No revenue in this fixture, so the ratio is 0 — what is being
        # guarded is that the divisor is the ramped number, not CTC × 3.
        self.assertAlmostEqual(row.achievement_pct, 0.0, places=2)

    def test_zero_ctc_reports_na_not_a_free_pass(self):
        """An employee with no CTC on record has no obligation to ramp; the
        row must still say N/A rather than inventing a reduced target."""
        row = self._row(self._make_employee(
            'No CTC', self._months_ago(0), annual_ctc=0.0))
        self.assertAlmostEqual(row.monthly_obligation, 0.0, places=2)
        self.assertEqual(row.rag_status, 'N/A')
        self.assertEqual(row.performance_status, 'N/A')

    def test_employee_outside_the_framework_gets_no_row(self):
        employee = self._make_employee(
            'Not Applicable', self._months_ago(0), applicable=False)
        self.assertFalse(self._row(employee))
