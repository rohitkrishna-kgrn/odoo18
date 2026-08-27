"""Tests for the timesheet-weighted revenue allocation (HR-PMS-001 §E1).

When several people work one engagement, the money collected against it is
divided between them in proportion to the hours each logged to the task —
not evenly, as it used to be — and that split is what the individual
performance scorecard (``mis.performance.line``) reports as Sales / Delivery
Revenue.

Unlike the Warning Notice tests, these drive the real SQL: the split lives in
``_TASK_WEIGHT_CTES`` and is consumed by three separate queries (the view
behind the scorecard, the drill-down breakdown and the date-filtered
recompute), so a fixture that actually reaches Postgres is the only thing
that proves all three agree.  Each test therefore builds a whole engagement —
order → project → task → timesheets → posted invoice → reconciled payment —
which is why every assertion below is on money that has genuinely been
collected.

The behaviours worth guarding:
  * the split follows logged hours, and nothing but logged hours;
  * every slice of a payment adds up to the payment — revenue is never
    duplicated across contributors, nor quietly lost;
  * a Revenue Role multiplier scales a contributor's hours when one is set;
  * hours count over the life of the task, not only the month the cash
    landed — otherwise whoever did the work months earlier gets nothing;
  * a partial payment is prorated first, then split;
  * the drill-down and the date-range recompute report the same shares as
    the scorecard itself.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

PRICE = 10000.0     # engagement value, ex-VAT


@tagged('post_install', '-at_install')
class TestRevenueAllocation(TransactionCase):

    # ── Fixture ──────────────────────────────────────────────────────────
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.today = fields.Date.today()
        cls.month = cls.today.replace(day=1)

        cls.product = cls.env['product.product'].create({
            'name': 'Alloc Test Engagement',
            'type': 'service',
            # billed up front, and never auto-spawning its own project/task
            'service_policy': 'ordered_prepaid',
            'service_tracking': 'no',
            'list_price': PRICE,
            'taxes_id': [(5, 0, 0)],        # no VAT: keeps the arithmetic exact
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Alloc Test Client'})

        cls.user_a, cls.emp_a = cls._make_member('Alloc Member A')
        cls.user_b, cls.emp_b = cls._make_member('Alloc Member B')
        cls.user_c, cls.emp_c = cls._make_member('Alloc Member C')

    @classmethod
    def _make_member(cls, name):
        login = name.lower().replace(' ', '.') + '@alloc.test'
        user = cls.env['res.users'].create({
            'name': name,
            'login': login,
            # crm_extended_rk only accepts a Dedicated Project Manager on an
            # engagement line, and these fixtures are the PMs of the story
            'is_dedicated_manager': True,
        })
        employee = cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'mis_performance_applicable': True,
            'mis_office_location': 'uae',
            'mis_performance_team': 'audit',
        })
        return user, employee

    def _engagement(self, price=PRICE):
        """One engagement: sale order line → project → task.

        The order is deliberately left in Draft.  Confirming it would drag in
        the whole KGRN approval workflow AND auto-create a second task on the
        same order line, which would change the very split under test.  None
        of the allocation SQL looks at the order's state — it reads the task's
        sale_line_id and the invoice lines linked to it — so a draft order is
        a faithful fixture.
        """
        order = self.env['sale.order'].with_context(
            skip_sales_team_check=True).create({
            'partner_id': self.partner.id,
            # proposal_workflow_extended_rk requires a CRM pipeline record or
            # this documented override, which it logs in the chatter
            'crm_link_override': True,
            'crm_link_override_reason': 'Automated revenue-allocation test',
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': price,
                'tax_id': [(5, 0, 0)],
                # the custom modules make these engagement fields mandatory
                # at database level, so a bare create() will not go through
                'manager_id': self.user_a.id,
                'engagement_start': self.today,
                'engagement_end': self.today + relativedelta(months=1),
                'deadline': self.today + relativedelta(months=1),
                'estimated_hours': 40.0,
            })],
        })
        project = self.env['project.project'].create({
            'name': 'Alloc Test Project',
            'partner_id': self.partner.id,
            'allow_timesheets': True,
            # project_extended_rk only accepts a Dedicated Project Manager
            'user_id': self.user_a.id,
            # so the contributors can read the task they are booking time to
            'privacy_visibility': 'employees',
        })
        task = self._task(project, order.order_line[0], 'Alloc Test Task')
        return order, project, task

    def _task(self, project, order_line, name):
        return self.env['project.task'].create({
            'name': name,
            'project_id': project.id,
            'sale_line_id': order_line.id,
            # project_extended_rk refuses timesheets unless the task is In
            # Progress, has room left in its allocation, and lists the person
            # doing the logging as a team member
            'state_additional': 'in_progress',
            'allocated_hours': 500.0,
            'team_member_ids': [(6, 0, (
                self.user_a | self.user_b | self.user_c).ids)],
        })

    def _log(self, task, employee, hours, date=None):
        # Logged AS the contributor: project_extended_rk only lets a task's
        # own team members book time to it, and the test superuser (OdooBot)
        # is an inactive user, so it can never be one of them.
        return self.env['account.analytic.line'].with_user(employee.user_id).create({
            'name': 'alloc test work',
            'project_id': task.project_id.id,
            'task_id': task.id,
            'employee_id': employee.id,
            'unit_amount': hours,
            'date': date or self.today,
        })

    def _invoice(self, order, date=None):
        """A posted customer invoice whose line is linked to the engagement's
        order line — the link (sale_order_line_invoice_rel) is what the
        allocation SQL follows from cash back to the task."""
        line = order.order_line[0]
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': date or self.today,
            # account_extended_rk refuses to post one without this
            'ar_responsible_id': self.user_a.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': line.price_unit,
                'tax_ids': [(5, 0, 0)],
                'sale_line_ids': [(6, 0, line.ids)],
            })],
        })
        invoice.action_post()
        return invoice

    def _pay(self, invoice, amount=None, date=None):
        """Reconcile a payment against a posted invoice — collection is what
        the scorecard counts, so nothing lands until this runs."""
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids,
        ).create({
            'payment_date': date or self.today,
            'amount': invoice.amount_total if amount is None else amount,
        })
        wizard._create_payments()
        return invoice

    def _collect(self, order, amount=None, date=None):
        """Invoice the engagement and reconcile a payment against it."""
        date = date or self.today
        return self._pay(self._invoice(order, date), amount=amount, date=date)

    def _mark_done(self, project, done_on=None):
        """Move the project into the Done stage — the boundary that turns
        collected cash from Sales Revenue into Delivery Revenue."""
        stage = self.env['project.project.stage'].search(
            [('name', '=', 'Done')], limit=1)
        self.assertTrue(stage, "this database has no 'Done' project stage")
        project.write({
            'stage_id': stage.id,
            'completed_date': done_on or (
                fields.Datetime.to_datetime(self.today) - relativedelta(days=1)),
        })
        self.assertEqual(project.stage_id, stage,
                         "fixture project did not reach the Done stage")
        return project

    # ── Reading the scorecard ────────────────────────────────────────────
    def _flush(self):
        """The scorecard is a SQL view over tables the ORM has no idea it
        reads, so pending writes must reach Postgres before it is queried —
        otherwise a role or a stage set moments earlier is simply invisible.
        In production every read arrives on a fresh RPC, so this is a test
        concern only."""
        self.env.flush_all()

    def _scorecard(self, user, month=None):
        self._flush()
        line = self.env['mis.performance.line'].sudo().search([
            ('user_id', '=', user.id),
            ('period_date', '=', month or self.month),
        ])
        self.assertEqual(
            len(line), 1,
            "expected exactly one scorecard row for %s in %s"
            % (user.name, month or self.month))
        return line

    def _revenue(self, user, month=None):
        return self._scorecard(user, month).total_revenue

    # ── The split itself ─────────────────────────────────────────────────
    def test_split_follows_logged_hours(self):
        """30h vs 10h on one task pays out 75/25, not 50/50."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE * 0.75, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE * 0.25, places=2)

    def test_shares_sum_to_the_collected_amount(self):
        """Three uneven contributors: 70/20/10, adding up to the whole."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 7)
        self._log(task, self.emp_b, 2)
        self._log(task, self.emp_c, 1)
        self._collect(order)

        a = self._revenue(self.user_a)
        b = self._revenue(self.user_b)
        c = self._revenue(self.user_c)
        self.assertAlmostEqual(a, PRICE * 0.70, places=2)
        self.assertAlmostEqual(b, PRICE * 0.20, places=2)
        self.assertAlmostEqual(c, PRICE * 0.10, places=2)
        self.assertAlmostEqual(a + b + c, PRICE, places=2,
                               msg="the split must neither duplicate nor lose revenue")

    def test_single_contributor_takes_the_whole_task(self):
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 4)
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), 0.0, places=2)

    def test_many_small_entries_aggregate_before_splitting(self):
        """The weight is total hours per person, not the number of entries."""
        order, _project, task = self._engagement()
        for _ in range(6):
            self._log(task, self.emp_a, 5)      # 30h over six entries
        self._log(task, self.emp_b, 10)         # 10h in one
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE * 0.75, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE * 0.25, places=2)

    def test_split_uses_lifetime_hours_not_the_payment_month(self):
        """Work done months before the cash arrives still earns its share."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30, date=self.today - relativedelta(months=2))
        self._log(task, self.emp_b, 10)
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE * 0.75, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE * 0.25, places=2)

    def test_hours_are_weighed_per_task_not_per_project(self):
        """Two tasks share one retainer line: the line's value is halved
        between the tasks (an older rule, unchanged), and only then is each
        half weighted by the hours logged to THAT task.  So a colleague's
        hours on a sibling task never dilute your share of your own."""
        order, project, task_a = self._engagement()
        task_b = self._task(project, order.order_line[0], 'Alloc Test Task 2')
        self._log(task_a, self.emp_a, 2)      # A alone on task A
        self._log(task_b, self.emp_b, 40)     # B alone on task B
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE / 2, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE / 2, places=2)

    def test_role_multiplier_scales_the_hours(self):
        """A Revenue Role, where set, weights the hours it is attached to."""
        trainee = self.env['mis.revenue.role'].create(
            {'name': 'Alloc Trainee', 'multiplier': 0.5})
        manager = self.env['mis.revenue.role'].create(
            {'name': 'Alloc Manager', 'multiplier': 2.0})
        self.emp_a.mis_revenue_role_id = trainee     # 30h x 0.5 = 15
        self.emp_b.mis_revenue_role_id = manager     # 10h x 2.0 = 20

        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE * 15 / 35, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE * 20 / 35, places=2)

    # ── Interaction with the collected-cash basis ────────────────────────
    def test_partial_payment_is_prorated_then_split(self):
        """40% collected on a 75/25 task pays 3,000 / 1,000."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order, amount=PRICE * 0.4)

        self.assertAlmostEqual(self._revenue(self.user_a), PRICE * 0.4 * 0.75, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), PRICE * 0.4 * 0.25, places=2)

    def test_unpaid_invoice_allocates_nothing(self):
        """Raising an invoice is not collecting it."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._invoice(order)

        self.assertAlmostEqual(self._revenue(self.user_a), 0.0, places=2)
        self.assertAlmostEqual(self._revenue(self.user_b), 0.0, places=2)

    def test_delivery_revenue_is_split_the_same_way(self):
        """Cash collected after the project is Done lands in Delivery
        Revenue — and is divided by the same weights."""
        order, project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        invoice = self._invoice(order)
        self._mark_done(project)
        self._pay(invoice)

        row_a = self._scorecard(self.user_a)
        row_b = self._scorecard(self.user_b)
        self.assertAlmostEqual(row_a.delivery_revenue, PRICE * 0.75, places=2)
        self.assertAlmostEqual(row_b.delivery_revenue, PRICE * 0.25, places=2)
        self.assertAlmostEqual(row_a.sales_revenue, 0.0, places=2)
        # Work Delivered is its own measure, but here the engagement was
        # delivered AND settled in full in the same month, so it happens to
        # carry the same weighted number.
        self.assertAlmostEqual(row_a.work_completed_value, PRICE * 0.75, places=2)

    def test_work_delivered_does_not_wait_for_payment(self):
        """Work Delivered is the value of work COMPLETED in the month, so it
        lands the month the project reaches Done — even when the client has
        not paid a dirham. This is what separates it from Delivery Revenue,
        which is cash and stays at zero until a payment reconciles."""
        order, project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._mark_done(project)        # delivered — but deliberately unpaid

        row_a = self._scorecard(self.user_a)
        row_b = self._scorecard(self.user_b)

        # the contracted value is recognised now, split on logged hours
        self.assertAlmostEqual(row_a.work_completed_value, PRICE * 0.75, places=2)
        self.assertAlmostEqual(row_b.work_completed_value, PRICE * 0.25, places=2)
        # and the shares still add up to the whole engagement
        self.assertAlmostEqual(
            row_a.work_completed_value + row_b.work_completed_value, PRICE, places=2)

        # none of the cash columns moved, because no cash has arrived
        self.assertAlmostEqual(row_a.delivery_revenue, 0.0, places=2)
        self.assertAlmostEqual(row_a.sales_revenue, 0.0, places=2)
        self.assertAlmostEqual(row_a.payments_collected_amount, 0.0, places=2)

    def test_work_delivered_is_silent_until_the_project_is_done(self):
        """The mirror of the test above: cash can arrive on an engagement
        that is still open, and Work Delivered must stay at zero until the
        project actually reaches Done."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 10)
        self._collect(order)            # invoiced and paid, but never Done

        row_a = self._scorecard(self.user_a)
        self.assertAlmostEqual(row_a.work_completed_value, 0.0, places=2)
        # the money is real and still counted — as an advance
        self.assertAlmostEqual(row_a.sales_revenue, PRICE, places=2)

    def test_invoices_and_collections_columns_use_the_same_weights(self):
        """Invoices Raised (AED) / Payments Collected (AED) are weighted
        alongside the revenue columns, so the row stays internally
        consistent — while the plain invoice COUNT stays whole."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        row_a = self._scorecard(self.user_a)
        row_b = self._scorecard(self.user_b)
        self.assertAlmostEqual(row_a.payments_collected_amount, PRICE * 0.75, places=2)
        self.assertAlmostEqual(row_b.payments_collected_amount, PRICE * 0.25, places=2)
        self.assertAlmostEqual(row_a.invoices_raised_amount, PRICE * 0.75, places=2)
        self.assertEqual(row_a.invoices_raised_count, 1,
                         "a fractional invoice count would be meaningless")
        self.assertEqual(row_b.invoices_raised_count, 1)

    # ── The two other queries that must agree with the view ──────────────
    def test_breakdown_explains_the_share(self):
        """The drill-down shows the hours behind the money."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        self._flush()
        data = self.env['mis.performance.line'].sudo().get_revenue_breakdown(
            self.emp_a.id, self.user_a.id, fields.Date.to_string(self.month))
        rows = [r for r in data['sales'] if r['task'] == task.name]
        self.assertEqual(len(rows), 1, "the task should appear exactly once")
        row = rows[0]
        self.assertAlmostEqual(row['hours'], 30.0, places=2)
        self.assertAlmostEqual(row['total_hours'], 40.0, places=2)
        self.assertAlmostEqual(row['share_pct'], 75.0, places=2)
        self.assertAlmostEqual(row['amount'], PRICE * 0.75, places=2)

    def test_breakdown_is_scoped_to_the_employee(self):
        """B's drill-down shows B's share, not A's."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        self._flush()
        data = self.env['mis.performance.line'].sudo().get_revenue_breakdown(
            self.emp_b.id, self.user_b.id, fields.Date.to_string(self.month))
        rows = [r for r in data['sales'] if r['task'] == task.name]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]['share_pct'], 25.0, places=2)
        self.assertAlmostEqual(rows[0]['amount'], PRICE * 0.25, places=2)
        self.assertAlmostEqual(data['sales_total'], PRICE * 0.25, places=2)

    def test_date_filtered_recompute_uses_the_same_weights(self):
        """The dashboard's Date filter narrows the window, not the split."""
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        Line = self.env['mis.performance.line'].sudo()
        row_a = self._scorecard(self.user_a)
        row_b = self._scorecard(self.user_b)
        month_end = self.month + relativedelta(day=31)
        amounts = Line.get_period_revenue_amounts(
            (row_a | row_b).ids,
            fields.Date.to_string(self.month),
            fields.Date.to_string(month_end))

        self.assertAlmostEqual(amounts[row_a.id]['total_revenue'], PRICE * 0.75, places=2)
        self.assertAlmostEqual(amounts[row_b.id]['total_revenue'], PRICE * 0.25, places=2)

    def test_date_filter_excluding_the_payment_shows_nothing(self):
        order, _project, task = self._engagement()
        self._log(task, self.emp_a, 30)
        self._log(task, self.emp_b, 10)
        self._collect(order)

        Line = self.env['mis.performance.line'].sudo()
        row_a = self._scorecard(self.user_a)
        # a window inside the month but ending before today's payment
        amounts = Line.get_period_revenue_amounts(
            row_a.ids,
            fields.Date.to_string(self.month),
            fields.Date.to_string(self.today - relativedelta(days=1)))
        self.assertAlmostEqual(
            amounts.get(row_a.id, {}).get('total_revenue', 0.0), 0.0, places=2)
