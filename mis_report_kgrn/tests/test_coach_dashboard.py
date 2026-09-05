"""Tests for the Coach Employee View (mis.coach.dashboard).

Two tiers, matching what's cheap vs. what genuinely needs the SQL view:

* Group-sync — plain ORM, no engagement fixture. group_mis_coach is never
  assigned by hand: whoever currently appears as someone's coach_id belongs
  to it, and nobody else does, recomputed from scratch on every relevant
  hr.employee create/write/unlink.
* Access-domain — a real engagement (order -> project -> task -> timesheet
  -> posted invoice), following the exact fixture recipe already proven in
  test_revenue_allocation.py for this database's custom constraints
  (crm_extended_rk / project_extended_rk / account_extended_rk all reject a
  bare fixture otherwise). Proves the coach sees exactly their coachee's
  project row with the right revenue/outstanding, an unrelated user sees
  nothing, and the admin sees everything.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

PRICE = 10000.0


@tagged('post_install', '-at_install')
class TestMisCoachGroupSync(TransactionCase):
    """Pure ORM — no view, no timesheet fixture needed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.group = cls.env.ref('mis_report_kgrn.group_mis_coach')

    def _make(self, name):
        user = self.env['res.users'].create({
            'name': name, 'login': name.lower().replace(' ', '.') + '@coach.test',
        })
        employee = self.env['hr.employee'].create({'name': name, 'user_id': user.id})
        return user, employee

    def test_write_coach_id_adds_coach_to_group(self):
        coach_user, coach_emp = self._make('Sync Coach A')
        _, coachee_emp = self._make('Sync Coachee A')
        self.assertNotIn(coach_user, self.group.users)

        coachee_emp.write({'coach_id': coach_emp.id})
        self.assertIn(coach_user, self.group.users)

    def test_create_with_coach_id_adds_coach_to_group(self):
        coach_user, coach_emp = self._make('Sync Coach B')
        self.env['hr.employee'].create({
            'name': 'Sync Coachee B', 'coach_id': coach_emp.id,
        })
        self.assertIn(coach_user, self.group.users)

    def test_clearing_only_coachee_drops_coach_from_group(self):
        coach_user, coach_emp = self._make('Sync Coach C')
        _, coachee_emp = self._make('Sync Coachee C')
        coachee_emp.write({'coach_id': coach_emp.id})
        self.assertIn(coach_user, self.group.users)

        coachee_emp.write({'coach_id': False})
        self.assertNotIn(coach_user, self.group.users)

    def test_archiving_only_coachee_drops_coach_from_group(self):
        coach_user, coach_emp = self._make('Sync Coach D')
        _, coachee_emp = self._make('Sync Coachee D')
        coachee_emp.write({'coach_id': coach_emp.id})
        self.assertIn(coach_user, self.group.users)

        coachee_emp.write({'active': False})
        self.assertNotIn(coach_user, self.group.users)

    def test_two_coachees_one_coach_yield_single_membership(self):
        coach_user, coach_emp = self._make('Sync Coach E')
        _, coachee_1 = self._make('Sync Coachee E1')
        _, coachee_2 = self._make('Sync Coachee E2')

        coachee_1.write({'coach_id': coach_emp.id})
        coachee_2.write({'coach_id': coach_emp.id})
        self.assertIn(coach_user, self.group.users)

        coachee_1.write({'coach_id': False})
        self.assertIn(coach_user, self.group.users, "coach E2 still coaches someone")
        coachee_2.write({'coach_id': False})
        self.assertNotIn(coach_user, self.group.users)

    def test_unrelated_write_does_not_touch_group(self):
        coach_user, coach_emp = self._make('Sync Coach F')
        _, coachee_emp = self._make('Sync Coachee F')
        coachee_emp.write({'coach_id': coach_emp.id})
        self.assertIn(coach_user, self.group.users)

        coachee_emp.write({'name': 'Sync Coachee F Renamed'})
        self.assertIn(coach_user, self.group.users)


@tagged('post_install', '-at_install')
class TestMisCoachDashboardAccess(TransactionCase):
    """One real engagement, following the recipe proven in
    test_revenue_allocation.py — the coach-dashboard view is built on top of
    mis.project.revenue.line and mis.project.wise, both of which need a
    posted, invoiced engagement to produce a row at all."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.today = fields.Date.today()
        cls.product = cls.env['product.product'].create({
            'name': 'Coach Test Engagement',
            'type': 'service',
            'service_policy': 'ordered_prepaid',
            'service_tracking': 'no',
            'list_price': PRICE,
            'taxes_id': [(5, 0, 0)],
        })
        cls.partner = cls.env['res.partner'].create({'name': 'Coach Test Client'})

        cls.coach_user, cls.coach_emp = cls._make_member('Coach Dash Coach')
        cls.coachee_user, cls.coachee_emp = cls._make_member('Coach Dash Coachee')
        cls.coachee_emp.write({'coach_id': cls.coach_emp.id})

        # A second, wholly unrelated coach — proves row-level isolation
        # between two legitimate coaches, not just the access-rights wall.
        cls.other_coach_user, cls.other_coach_emp = cls._make_member('Coach Dash Other Coach')
        _, other_coachee_emp = cls._make_member('Coach Dash Other Coachee')
        other_coachee_emp.write({'coach_id': cls.other_coach_emp.id})

        # A plain internal user with no MIS group at all — this model must
        # stay invisible to them, same as it is today (no menu, no data).
        cls.outsider_user = cls.env['res.users'].create({
            'name': 'Coach Dash Outsider',
            'login': 'coach.dash.outsider@coachdash.test',
        })

        # A real, active user in group_mis_admin — the tests run as
        # OdooBot by default, and the superuser bypasses ir.rule/ir.model.
        # access entirely, so exercising the Admin rule needs a real login.
        cls.admin_user = cls.env['res.users'].create({
            'name': 'Coach Dash Admin', 'login': 'coach.dash.admin@coachdash.test',
        })
        cls.env.ref('mis_report_kgrn.group_mis_admin').sudo().write({
            'users': [(4, cls.admin_user.id)],
        })

    @classmethod
    def _make_member(cls, name):
        login = name.lower().replace(' ', '.') + '@coachdash.test'
        user = cls.env['res.users'].create({
            'name': name, 'login': login, 'is_dedicated_manager': True,
        })
        employee = cls.env['hr.employee'].create({'name': name, 'user_id': user.id})
        return user, employee

    def _flush(self):
        self.env.flush_all()

    def _build_engagement(self):
        order = self.env['sale.order'].with_context(
            skip_sales_team_check=True).create({
            'partner_id': self.partner.id,
            'crm_link_override': True,
            'crm_link_override_reason': 'Automated coach-dashboard test',
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': PRICE,
                'tax_id': [(5, 0, 0)],
                'manager_id': self.coach_user.id,
                'engagement_start': self.today,
                'engagement_end': self.today + relativedelta(months=1),
                'deadline': self.today + relativedelta(months=1),
                'estimated_hours': 40.0,
            })],
        })
        project = self.env['project.project'].create({
            'name': 'Coach Dash Test Project',
            'partner_id': self.partner.id,
            'allow_timesheets': True,
            'user_id': self.coach_user.id,
            'privacy_visibility': 'employees',
        })
        task = self.env['project.task'].create({
            'name': 'Coach Dash Test Task',
            'project_id': project.id,
            'sale_line_id': order.order_line[0].id,
            'state_additional': 'in_progress',
            'allocated_hours': 500.0,
            'team_member_ids': [(6, 0, self.coachee_user.ids)],
        })
        self.env['account.analytic.line'].with_user(self.coachee_user).create({
            'name': 'coach dash test work',
            'project_id': project.id,
            'task_id': task.id,
            'employee_id': self.coachee_emp.id,
            'unit_amount': 8.0,
            'date': self.today,
        })
        line = order.order_line[0]
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.today,
            'ar_responsible_id': self.coach_user.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': line.price_unit,
                'tax_ids': [(5, 0, 0)],
                'sale_line_ids': [(6, 0, line.ids)],
            })],
        })
        invoice.action_post()
        return order, project, task, invoice

    def test_coach_sees_only_own_coachee_project(self):
        order, project, task, invoice = self._build_engagement()
        self._flush()

        wise_row = self.env['mis.project.wise'].sudo().search(
            [('project_id', '=', project.id)])
        self.assertTrue(wise_row, "fixture project has no mis.project.wise row")

        Dashboard = self.env['mis.coach.dashboard']
        coach_rows = Dashboard.with_user(self.coach_user).search(
            [('project_id', '=', project.id)])
        self.assertEqual(len(coach_rows), 1)
        self.assertEqual(coach_rows.employee_id, self.coachee_emp)
        self.assertEqual(coach_rows.project_revenue_ex_vat, wise_row.so_total_ex_vat)
        self.assertEqual(coach_rows.outstanding_ex_vat, wise_row.outstanding_ex_vat)
        # invoiced but not paid: something is genuinely outstanding
        self.assertGreater(coach_rows.outstanding_ex_vat, 0)

    def test_other_coach_does_not_see_this_coachee(self):
        """The row-level check that matters: two real coaches, each scoped
        to only their own assigned employees."""
        order, project, task, invoice = self._build_engagement()
        self._flush()

        rows = self.env['mis.coach.dashboard'].with_user(self.other_coach_user).search(
            [('project_id', '=', project.id)])
        self.assertFalse(rows)

    def test_plain_user_has_no_model_access(self):
        """A non-coach, non-admin user has no ir.model.access entry at all
        for this model — the menu is hidden from them and a direct search
        must raise, not silently return an empty list."""
        order, project, task, invoice = self._build_engagement()
        self._flush()

        with self.assertRaises(AccessError):
            self.env['mis.coach.dashboard'].with_user(self.outsider_user).search(
                [('project_id', '=', project.id)])

    def test_admin_sees_the_row_too(self):
        order, project, task, invoice = self._build_engagement()
        self._flush()

        rows = self.env['mis.coach.dashboard'].with_user(self.admin_user).search(
            [('project_id', '=', project.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.coach_user_id, self.coach_user)
