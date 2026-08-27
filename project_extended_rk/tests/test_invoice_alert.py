"""Tests for the engagement-level overdue / unreconciled invoice indicator.

The two things worth guarding are the state machine (which colour for which
invoice position) and the access story: the whole feature exists so that a
Project Manager with no rights on ``account.move`` can still see the flag and
the invoice detail behind it. ``test_flag_readable_without_accounting_rights``
is the one that would have caught the AccessError this design was built to
avoid.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError


@tagged('post_install', '-at_install')
class TestEngagementInvoiceAlert(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env['project.project'])
        cls.partner = cls.env['res.partner'].create({'name': 'Alert Test Client'})
        # crm_extended_rk constrains sale_order_line.manager_id to users flagged
        # as Dedicated Project Managers, so the fixture needs a real one.
        cls.manager = cls.env['res.users'].create({
            'name': 'Alert Test Engagement Manager',
            'login': 'alert_test_engagement_manager',
            'is_dedicated_manager': True,
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('project.group_project_manager').id,
            ])],
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Audit Service',
            'type': 'service',
            'invoice_policy': 'order',
            'list_price': 1000.0,
        })

    # --- helpers ---------------------------------------------------------
    def _make_engagement(self, name='SE99001', pm=None):
        """A sale order plus the project that bills through it."""
        cls_today = self.today
        # sale_renewal_rk blocks sale order creation for non-Sales-Team users;
        # skip_sales_team_check is the hook it provides for automated creation.
        order = self.env['sale.order'].with_context(
            skip_sales_team_check=True
        ).create({
            'name': name,
            'partner_id': self.partner.id,
            # proposal_workflow_extended_rk requires a CRM pipeline record on new
            # quotations; this is the documented override for the exceptions.
            'crm_link_override': True,
            'crm_link_override_reason': 'Automated test fixture',
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 1000.0,
                # These four are NOT NULL on sale_order_line in this
                # database, added by the custom engagement modules.
                'manager_id': self.manager.id,
                'deadline': cls_today,
                'engagement_start': cls_today,
                'engagement_end': cls_today,
                'estimated_hours': 1.0,
            })],
        })
        order.action_confirm()
        project = self.env['project.project'].create({
            'name': '%s - Statutory Audit' % name,
            'partner_id': self.partner.id,
            # project.py constrains user_id the same way sale_order_line does,
            # and its write() blocks reassigning the PM afterwards - so the
            # PM has to be set at creation.
            'user_id': (pm or self.manager).id,
            'engagement_order_id': order.id,
        })
        return order, project

    def _invoice(self, order, due_offset_days, post=True, paid=False):
        """Raise one invoice on the order, due ``due_offset_days`` from today."""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.today,
            # account_extended_rk makes this mandatory on customer invoices.
            'ar_responsible_id': self.manager.id,
            'invoice_date_due': self.today + timedelta(days=due_offset_days),
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 1000.0,
                'sale_line_ids': [(6, 0, order.order_line.ids)],
            })],
        })
        if post:
            invoice.action_post()
        if paid:
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids
            ).create({
                'payment_date': self.today,
            })._create_payments()
        return invoice

    # --- state machine ---------------------------------------------------
    def test_no_invoice_is_grey(self):
        _order, project = self._make_engagement('SE99001')
        self.assertEqual(project.invoice_alert_state, 'none')
        self.assertEqual(project.overdue_invoice_count, 0)
        self.assertIn('No customer invoice', project.invoice_alert_summary)

    def test_overdue_invoice_is_red(self):
        order, project = self._make_engagement('SE99002')
        invoice = self._invoice(order, due_offset_days=-30)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'overdue')
        self.assertEqual(project.overdue_invoice_count, 1)
        # The flag reports what is left to collect, tax included.
        self.assertEqual(project.overdue_invoice_amount, invoice.amount_residual)
        self.assertEqual(project.invoice_days_overdue, 30)
        # An overdue invoice is unreconciled too — it is counted in both.
        self.assertEqual(project.unreconciled_invoice_count, 1)

    def test_unreconciled_but_not_yet_due_is_amber(self):
        order, project = self._make_engagement('SE99003')
        invoice = self._invoice(order, due_offset_days=30)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'warning')
        self.assertEqual(project.overdue_invoice_count, 0)
        self.assertEqual(project.unreconciled_invoice_count, 1)
        self.assertEqual(project.unreconciled_invoice_amount, invoice.amount_residual)

    def test_draft_invoice_is_amber(self):
        order, project = self._make_engagement('SE99004')
        self._invoice(order, due_offset_days=-30, post=False)
        project.invalidate_recordset()
        # Never posted, so there is no receivable to be late on: amber, not red.
        self.assertEqual(project.invoice_alert_state, 'warning')
        self.assertEqual(project.overdue_invoice_count, 0)
        self.assertEqual(project.draft_invoice_count, 1)
        self.assertIn('still in draft', project.invoice_alert_summary)

    def test_fully_paid_invoice_is_green(self):
        order, project = self._make_engagement('SE99005')
        self._invoice(order, due_offset_days=-30, paid=True)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'ok')
        self.assertEqual(project.overdue_invoice_count, 0)
        self.assertEqual(project.unreconciled_invoice_count, 0)

    def test_red_wins_over_amber(self):
        order, project = self._make_engagement('SE99006')
        pending = self._invoice(order, due_offset_days=30)    # amber on its own
        overdue = self._invoice(order, due_offset_days=-10)   # red
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'overdue')
        self.assertEqual(project.overdue_invoice_count, 1)
        self.assertEqual(project.unreconciled_invoice_count, 2)
        self.assertEqual(
            project.unreconciled_invoice_amount,
            pending.amount_residual + overdue.amount_residual,
        )

    def test_oldest_overdue_drives_the_age(self):
        order, project = self._make_engagement('SE99007')
        self._invoice(order, due_offset_days=-5)
        self._invoice(order, due_offset_days=-120)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_days_overdue, 120)
        self.assertEqual(project.overdue_invoice_count, 2)

    def test_cancelled_invoice_is_ignored(self):
        order, project = self._make_engagement('SE99008')
        invoice = self._invoice(order, due_offset_days=-30)
        invoice.button_cancel()
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'none')

    def test_flag_clears_when_the_invoice_is_paid(self):
        """The stored flag must follow a payment without a manual recompute."""
        order, project = self._make_engagement('SE99009')
        invoice = self._invoice(order, due_offset_days=-30)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'overdue')

        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids
        ).create({'payment_date': self.today})._create_payments()

        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'ok')
        self.assertEqual(project.overdue_invoice_amount, 0.0)

    def test_partial_payment_stays_red(self):
        order, project = self._make_engagement('SE99010')
        invoice = self._invoice(order, due_offset_days=-30)
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids
        ).create({
            'payment_date': self.today,
            'amount': 400.0,
        })._create_payments()
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'overdue')
        self.assertEqual(project.overdue_invoice_amount, invoice.amount_residual)

    def test_invoice_linked_through_the_task_sale_line(self):
        """Older projects carry no engagement order — the task's line links them."""
        order, project = self._make_engagement('SE99011')
        project.engagement_order_id = False
        self.env['project.task'].create({
            'name': 'Fieldwork',
            'project_id': project.id,
            'sale_line_id': order.order_line[0].id,
        })
        self._invoice(order, due_offset_days=-15)
        project.invalidate_recordset()
        self.assertEqual(project.invoice_alert_state, 'overdue')

    # --- the access story ------------------------------------------------
    def test_flag_readable_without_accounting_rights(self):
        """A PM with no rights on account.move must still see the flag.

        This is the requirement the whole design turns on: the indicator has to
        work for the PM, team lead and department head *without* them opening
        the invoice module. Reading account.move directly is asserted to fail so
        the test proves the sudo() in the compute is what is doing the work, not
        an incidental access right on the test user.
        """
        pm = self.env['res.users'].create({
            'name': 'Project Manager No Accounting',
            'login': 'pm_no_accounting_alert_test',
            'is_dedicated_manager': True,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('project.group_project_manager').id,
            ])],
        })
        order, project = self._make_engagement('SE99012', pm=pm)
        invoice = self._invoice(order, due_offset_days=-45)
        project.invalidate_recordset()

        with self.assertRaises(AccessError):
            invoice.with_user(pm).read(['amount_residual'])

        as_pm = project.with_user(pm)
        self.assertEqual(as_pm.invoice_alert_state, 'overdue')
        self.assertEqual(as_pm.overdue_invoice_count, 1)
        self.assertEqual(as_pm.overdue_invoice_amount, invoice.amount_residual)
        self.assertEqual(as_pm.invoice_days_overdue, 45)
        # ...and the detail behind the flag, without the invoice module.
        self.assertIn(invoice.name, as_pm.invoice_alert_summary)

    def test_search_and_group_by_the_flag(self):
        """The stored field must be searchable — the triage filters rely on it."""
        order, project = self._make_engagement('SE99013')
        self._invoice(order, due_offset_days=-30)
        project.invalidate_recordset()

        found = self.env['project.project'].search([
            ('id', '=', project.id),
            ('invoice_alert_state', '=', 'overdue'),
        ])
        self.assertEqual(found, project)

        groups = self.env['project.project']._read_group(
            [('id', '=', project.id)],
            groupby=['invoice_alert_state'],
            aggregates=['__count'],
        )
        self.assertEqual(groups[0][0], 'overdue')
