"""Acceptance tests for the Engagement Letter Tracking dashboard.

The requirement this suite verifies, clause by clause:

    "One view showing all active client service engagements with: engagement
     letter sent (Y/N), client signed (Y/N), date signed, advance fee invoice
     status, and project start date. Must support filters by team, PM and
     status."

Every clause has at least one test and the section comments name the clause.
The dashboard itself is ``project_extended_rk.action_engagement_tracking``
(Project -> Reporting -> Engagement Letter Tracking), built on
``project.project`` because the PM, team, start date and customer all live on
the project and not on the sale order.

Fixture note: creating a sale order in this database means clearing guards from
five different custom modules — see ``_make_engagement`` for what each one is
for. Nothing here touches production data: a TransactionCase rolls its whole
transaction back, so the SE98xxx engagements below never reach the tables.
"""

from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestEngagementLetterTracking(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Project = cls.env['project.project']
        cls.today = fields.Date.context_today(cls.Project)
        cls.now = fields.Datetime.now()
        cls.partner = cls.env['res.partner'].create({'name': 'EL Tracking Client'})
        cls.product = cls.env['product.product'].create({
            'name': 'EL Tracking Audit Service',
            'type': 'service',
            'invoice_policy': 'order',
            'list_price': 1000.0,
        })

        # Two teams with a PM each: the "filter by team" clause needs the
        # project's department_id to be populated, and that field is computed
        # from the *employee* record behind the PM user — so the employee has
        # to exist before the project is created, or the stored value is empty.
        cls.team_audit = cls.env['hr.department'].create({'name': 'EL Audit Team'})
        cls.team_tax = cls.env['hr.department'].create({'name': 'EL Tax Team'})
        cls.pm_audit = cls._make_pm('EL Audit PM', 'el_audit_pm', cls.team_audit)
        cls.pm_tax = cls._make_pm('EL Tax PM', 'el_tax_pm', cls.team_tax)
        cls.manager = cls.pm_audit

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    @classmethod
    def _make_pm(cls, name, login, department):
        """A Dedicated Project Manager with an employee record in ``department``."""
        user = cls.env['res.users'].create({
            'name': name,
            'login': login,
            # crm_extended_rk / project_extended_rk both refuse a PM that is not
            # flagged as a Dedicated Project Manager.
            'is_dedicated_manager': True,
            'groups_id': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('project.group_project_manager').id,
            ])],
        })
        cls.env['hr.employee'].create({
            'name': name,
            'user_id': user.id,
            'department_id': department.id,
        })
        return user

    def _make_order(self, code, advance=0.0):
        order = self.env['sale.order'].with_context(
            # sale_renewal_rk blocks order creation outside the sales team;
            # this is its documented automation hook.
            skip_sales_team_check=True,
        ).create({
            'name': code,
            'partner_id': self.partner.id,
            # proposal_workflow_extended_rk requires a CRM pipeline record on
            # every new quotation unless the override is given.
            'crm_link_override': True,
            'crm_link_override_reason': 'Engagement letter tracking test fixture',
            'advance_amount': advance,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 1000.0,
                # NOT NULL on sale_order_line in this database.
                'manager_id': self.manager.id,
                'deadline': self.today,
                'engagement_start': self.today,
                'engagement_end': self.today,
                'estimated_hours': 1.0,
            })],
        })
        # Deliberately left in draft: project_extended_rk.action_confirm returns
        # an advance-confirmation wizard instead of confirming, and confirming
        # would auto-create a second project on the same line.
        return order

    def _make_project(self, name, pm=None, date_start=None, **vals):
        values = {
            'name': name,
            'partner_id': self.partner.id,
            # project.write() refuses to reassign the PM afterwards, so it has
            # to be right at creation time.
            'user_id': (pm or self.pm_audit).id,
            'date_start': date_start or self.today,
        }
        values.update(vals)
        return self.Project.create(values)

    def _make_engagement(self, code, pm=None, advance=0.0, date_start=None):
        """One sale order + the project that represents that engagement."""
        order = self._make_order(code, advance=advance)
        project = self._make_project(
            '%s - Statutory Audit' % code, pm=pm, date_start=date_start)
        return order, project

    def _invoice(self, order, post=True, paid=None, advance_flag=False):
        """Raise one customer invoice on the engagement's order line."""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'invoice_date': self.today,
            'invoice_date_due': self.today + timedelta(days=30),
            # account_extended_rk makes this mandatory on customer invoices.
            'ar_responsible_id': self.manager.id,
            'advance_invoice': advance_flag,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 1000.0,
                # This m2m *is* sale_order_line_invoice_rel, the link the
                # dashboard's advance-invoice resolver walks.
                'sale_line_ids': [(6, 0, order.order_line.ids)],
            })],
        })
        if post:
            invoice.action_post()
        if paid is not None:
            self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=invoice.ids
            ).create(
                {'payment_date': self.today}
                if paid is True else
                {'payment_date': self.today, 'amount': paid}
            )._create_payments()
        return invoice

    # ==================================================================
    # Clause: "all active client service engagements" — the engagement link
    # ==================================================================
    def test_engagement_resolved_from_the_linked_sale_order_line(self):
        order = self._make_order('SE98001')
        project = self._make_project('Handwritten Audit Project')
        project.sale_line_id = order.order_line[0].id
        project.invalidate_recordset()
        self.assertEqual(project.engagement_order_id, order)

    def test_engagement_resolved_from_the_se_code_in_the_project_name(self):
        """Only 9 of 3,161 live projects carry sale_line_id — the name is the link."""
        order, project = self._make_engagement('SE98002')
        self.assertEqual(project.engagement_order_id, order)

    def test_engagement_resolved_despite_zero_width_and_punctuation(self):
        """Several live project names start with a zero-width space."""
        order = self._make_order('SE98003')
        project = self._make_project('​SE-98003 – Statutory Audit')
        self.assertEqual(project.engagement_order_id, order)

    def test_project_without_an_se_code_reports_no_engagement(self):
        project = self._make_project('Internal Housekeeping Project')
        self.assertFalse(project.engagement_order_id)
        self.assertEqual(project.engagement_status, 'no_order')

    def test_archived_engagement_leaves_the_dashboard(self):
        """The dashboard is 'all *active* engagements' — the active filter is it."""
        _order, project = self._make_engagement('SE98004')
        self.assertIn(project, self.Project.search([('id', '=', project.id)]))
        project.write({'active': False})
        self.assertFalse(self.Project.search([('id', '=', project.id)]))
        self.assertIn(
            project,
            self.Project.with_context(active_test=False).search([('id', '=', project.id)]),
        )

    # ==================================================================
    # Clause: "engagement letter sent (Y/N)"
    # ==================================================================
    def test_letter_sent_follows_the_generated_agreement(self):
        order, project = self._make_engagement('SE98010')
        self.assertFalse(project.engagement_letter_sent)
        self.assertEqual(project.engagement_status, 'not_sent')

        order.se_generated_on = self.now
        project.invalidate_recordset()
        self.assertTrue(project.engagement_letter_sent)
        self.assertEqual(project.engagement_letter_sent_date, self.now)
        self.assertEqual(project.engagement_status, 'awaiting_signature')

    def test_letter_sent_can_be_recorded_by_hand(self):
        """Nobody uses the Download SE button, so paper letters are typed in."""
        _order, project = self._make_engagement('SE98011')
        manual = self.now - timedelta(days=10)
        project.engagement_letter_sent_date = manual
        self.assertTrue(project.engagement_letter_sent)
        self.assertEqual(project.engagement_letter_sent_date, manual)

    def test_a_manual_sent_date_is_never_wiped_by_the_recompute(self):
        order, project = self._make_engagement('SE98012')
        manual = self.now - timedelta(days=10)
        project.engagement_letter_sent_date = manual
        # Touch a dependency so the stored compute runs again.
        order.advance_amount = 1.0
        project.invalidate_recordset()
        self.assertEqual(project.engagement_letter_sent_date, manual)

    def test_a_signed_letter_counts_as_sent(self):
        """Signed letters whose send date was never recorded must not read 'Not Sent'."""
        order, project = self._make_engagement('SE98013')
        order.signed_on = self.now
        project.invalidate_recordset()
        self.assertFalse(project.engagement_letter_sent_date)
        self.assertTrue(project.engagement_letter_sent)
        self.assertEqual(project.engagement_status, 'signed')

    # ==================================================================
    # Clause: "client signed (Y/N)" and "date signed"
    # ==================================================================
    def test_signature_flag_date_and_signatory(self):
        order, project = self._make_engagement('SE98020')
        self.assertFalse(project.engagement_letter_signed)
        self.assertFalse(project.engagement_letter_signed_date)

        order.se_generated_on = self.now - timedelta(days=5)
        order.signed_on = self.now
        order.signed_by = 'A. Client Director'
        project.invalidate_recordset()

        self.assertTrue(project.engagement_letter_signed)
        self.assertEqual(project.engagement_letter_signed_date, self.now)
        self.assertEqual(project.engagement_signed_by, 'A. Client Director')
        self.assertEqual(project.engagement_status, 'signed')

    def test_signature_can_be_recorded_by_hand_for_paper_letters(self):
        _order, project = self._make_engagement('SE98021')
        manual = self.now - timedelta(days=3)
        project.engagement_letter_signed_date = manual
        self.assertTrue(project.engagement_letter_signed)
        self.assertEqual(project.engagement_letter_signed_date, manual)
        self.assertEqual(project.engagement_status, 'signed')

    def test_a_manual_signature_date_is_never_wiped_by_the_recompute(self):
        order, project = self._make_engagement('SE98022')
        manual = self.now - timedelta(days=3)
        project.engagement_letter_signed_date = manual
        order.advance_amount = 1.0
        project.invalidate_recordset()
        self.assertEqual(project.engagement_letter_signed_date, manual)

    def test_status_walks_the_whole_letter_lifecycle(self):
        order, project = self._make_engagement('SE98023')
        self.assertEqual(project.engagement_status, 'not_sent')

        order.se_generated_on = self.now - timedelta(days=2)
        project.invalidate_recordset()
        self.assertEqual(project.engagement_status, 'awaiting_signature')

        order.signed_on = self.now
        project.invalidate_recordset()
        self.assertEqual(project.engagement_status, 'signed')

    # ==================================================================
    # Clause: "advance fee invoice status"
    # ==================================================================
    def test_advance_not_required_when_no_advance_was_agreed(self):
        _order, project = self._make_engagement('SE98030', advance=0.0)
        self.assertEqual(project.advance_invoice_status, 'not_required')
        self.assertFalse(project.advance_invoice_id)

    def test_advance_not_raised(self):
        _order, project = self._make_engagement('SE98031', advance=500.0)
        self.assertEqual(project.advance_invoice_status, 'not_created')
        self.assertFalse(project.advance_invoice_id)

    def test_advance_draft(self):
        order, project = self._make_engagement('SE98032', advance=500.0)
        invoice = self._invoice(order, post=False)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'draft')
        self.assertEqual(project.advance_invoice_id, invoice)

    def test_advance_posted_but_unpaid(self):
        order, project = self._make_engagement('SE98033', advance=500.0)
        invoice = self._invoice(order)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'posted')
        self.assertEqual(project.advance_invoice_id, invoice)

    def test_advance_partially_paid(self):
        order, project = self._make_engagement('SE98034', advance=500.0)
        self._invoice(order, paid=400.0)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'partial')

    def test_advance_paid(self):
        order, project = self._make_engagement('SE98035', advance=500.0)
        self._invoice(order, paid=True)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'paid')

    def test_status_follows_the_payment_without_a_manual_recompute(self):
        """The badge is a stored field — it has to move on its own."""
        order, project = self._make_engagement('SE98036', advance=500.0)
        invoice = self._invoice(order)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'posted')

        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids
        ).create({'payment_date': self.today})._create_payments()

        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'paid')

    def test_the_first_invoice_is_taken_as_the_advance(self):
        """account_move.advance_invoice is True on 0 live rows — this is the fallback."""
        order, project = self._make_engagement('SE98037', advance=500.0)
        first = self._invoice(order)
        self._invoice(order)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_id, first)

    def test_an_explicitly_flagged_advance_invoice_wins(self):
        order, project = self._make_engagement('SE98038', advance=500.0)
        self._invoice(order)
        flagged = self._invoice(order, advance_flag=True)
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_id, flagged)

    def test_a_cancelled_invoice_does_not_count_as_the_advance(self):
        order, project = self._make_engagement('SE98039', advance=500.0)
        invoice = self._invoice(order)
        invoice.button_cancel()
        project.invalidate_recordset()
        self.assertEqual(project.advance_invoice_status, 'not_created')
        self.assertFalse(project.advance_invoice_id)

    # ==================================================================
    # Clause: "project start date"
    # ==================================================================
    def test_project_start_date_is_reported_and_filterable(self):
        start = self.today - timedelta(days=45)
        _order, project = self._make_engagement('SE98040', date_start=start)
        self.assertEqual(project.date_start, start)
        found = self.Project.search([
            ('id', '=', project.id),
            ('date_start', '>=', start),
            ('date_start', '<=', start),
        ])
        self.assertEqual(found, project)

    # ==================================================================
    # Clause: "must support filters by team, PM and status"
    # ==================================================================
    def test_filter_by_team(self):
        _o1, audit = self._make_engagement('SE98050', pm=self.pm_audit)
        _o2, tax = self._make_engagement('SE98051', pm=self.pm_tax)
        self.assertEqual(audit.department_id, self.team_audit)
        self.assertEqual(tax.department_id, self.team_tax)

        in_audit = self.Project.search([
            ('id', 'in', (audit + tax).ids),
            ('department_id', '=', self.team_audit.id),
        ])
        self.assertEqual(in_audit, audit)

    def test_filter_by_project_manager(self):
        _o1, mine = self._make_engagement('SE98052', pm=self.pm_audit)
        _o2, theirs = self._make_engagement('SE98053', pm=self.pm_tax)

        found = self.Project.search([
            ('id', 'in', (mine + theirs).ids),
            ('user_id', '=', self.pm_audit.id),
        ])
        self.assertEqual(found, mine)

        # ...and the "My Engagements" filter, evaluated as that PM would.
        as_pm = self.Project.with_user(self.pm_audit).search([
            ('id', 'in', (mine + theirs).ids),
            ('user_id', '=', self.pm_audit.id),
        ])
        self.assertEqual(as_pm, mine)

    def test_filter_by_status(self):
        order_sent, sent = self._make_engagement('SE98054')
        order_signed, signed = self._make_engagement('SE98055')
        _order_new, not_sent = self._make_engagement('SE98056')
        order_sent.se_generated_on = self.now
        order_signed.signed_on = self.now
        (sent + signed + not_sent).invalidate_recordset()
        scope = (sent + signed + not_sent).ids

        expected = {
            'not_sent': not_sent,
            'awaiting_signature': sent,
            'signed': signed,
        }
        for status, project in expected.items():
            found = self.Project.search([
                ('id', 'in', scope), ('engagement_status', '=', status)])
            self.assertEqual(found, project, "status filter %r" % status)

        # The Y/N columns are searchable in their own right too.
        self.assertEqual(
            self.Project.search([('id', 'in', scope), ('engagement_letter_sent', '=', True)]),
            sent + signed,
        )
        self.assertEqual(
            self.Project.search([('id', 'in', scope), ('engagement_letter_signed', '=', False)]),
            sent + not_sent,
        )

    def test_group_by_team_pm_and_status(self):
        _o1, audit = self._make_engagement('SE98057', pm=self.pm_audit)
        _o2, tax = self._make_engagement('SE98058', pm=self.pm_tax)
        scope = [('id', 'in', (audit + tax).ids)]

        for groupby, expected in (
            ('department_id', {self.team_audit.id, self.team_tax.id}),
            ('user_id', {self.pm_audit.id, self.pm_tax.id}),
            ('engagement_status', {'not_sent'}),
            ('advance_invoice_status', {'not_required'}),
        ):
            groups = self.Project._read_group(scope, groupby=[groupby], aggregates=['__count'])
            values = {g[0].id if hasattr(g[0], 'id') else g[0] for g in groups}
            self.assertEqual(values, expected, "group by %r" % groupby)

    def test_every_filter_shipped_in_the_search_view_is_executable(self):
        """A typo in a filter domain only shows up when somebody clicks it."""
        view = self.env.ref('project_extended_rk.view_engagement_tracking_search')
        arch = etree.fromstring(view.arch)
        eval_context = {
            'uid': self.env.uid,
            'context_today': lambda: self.today,
            'current_date': fields.Date.to_string(self.today),
            'allowed_company_ids': self.env.companies.ids,
        }

        filters = arch.xpath('//filter[@domain]')
        self.assertTrue(filters, "the dashboard search view lost its filters")
        for node in filters:
            name = node.get('name')
            domain = safe_eval(node.get('domain'), eval_context)
            # Raises if the domain names a field that does not exist.
            self.Project.search(domain, limit=1)

        for node in arch.xpath('//filter[@context]'):
            context = safe_eval(node.get('context'), eval_context)
            groupby = context.get('group_by')
            if not groupby:
                continue
            field = groupby.split(':')[0]
            self.assertIn(field, self.Project._fields,
                          "group-by filter %r targets a missing field" % node.get('name'))
            # A bare date group-by is illegal in _read_group, but the web client
            # never sends one: search_model.js stamps DEFAULT_INTERVAL ("month")
            # on any dateGroupBy that carries no granularity. Mirror that here,
            # otherwise the test fails on a filter that works perfectly in the UI.
            if ':' not in groupby and self.Project._fields[field].type in ('date', 'datetime'):
                groupby = '%s:month' % groupby
            self.Project._read_group([('id', '=', 0)], groupby=[groupby], aggregates=['__count'])

        # The three filter axes the requirement calls out must all be offered.
        searchable = {n.get('name') for n in arch.xpath('//field[@name]')}
        groupbys = {n.get('name') for n in arch.xpath('//filter[@context]')}
        self.assertLessEqual({'user_id', 'department_id'}, searchable)
        self.assertLessEqual({'group_team', 'group_pm', 'group_status'}, groupbys)
        self.assertTrue({n.get('name') for n in filters} >= {
            'el_not_sent', 'el_sent', 'el_awaiting_signature', 'el_signed', 'el_not_signed'})

    # ==================================================================
    # Clause: "one view" — the dashboard is actually wired up
    # ==================================================================
    def test_the_dashboard_action_and_menu_are_wired_up(self):
        action = self.env.ref('project_extended_rk.action_engagement_tracking')
        self.assertEqual(action.res_model, 'project.project')
        self.assertEqual(
            action.search_view_id,
            self.env.ref('project_extended_rk.view_engagement_tracking_search'),
        )
        menu = self.env.ref('project_extended_rk.menu_engagement_tracking')
        self.assertEqual(menu.action.id, action.id)
        self.assertEqual(menu.parent_id, self.env.ref('project.menu_project_report'))

        # The list view bound to the action is the tracking one, not core's.
        bound = self.env.ref('project_extended_rk.action_engagement_tracking_list_view')
        self.assertEqual(
            bound.view_id, self.env.ref('project_extended_rk.view_engagement_tracking_list'))

    def test_the_list_view_carries_every_requested_column(self):
        view = self.env.ref('project_extended_rk.view_engagement_tracking_list')
        arch = etree.fromstring(view.arch)
        shown = {n.get('name') for n in arch.xpath('//field[@name]')}
        required = {
            'engagement_letter_sent',          # letter sent (Y/N)
            'engagement_letter_signed',        # client signed (Y/N)
            'engagement_letter_signed_date',   # date signed
            'advance_invoice_status',          # advance fee invoice status
            'date_start',                      # project start date
            'user_id',                         # PM (filter axis)
            'department_id',                   # team (filter axis)
            'engagement_status',               # status (filter axis)
        }
        self.assertLessEqual(required, shown)
        for name in shown:
            self.assertIn(name, self.Project._fields,
                          "list view shows a field that does not exist: %r" % name)

        # And the whole thing renders — this is what catches a bad widget or
        # a decoration referring to a field the view never loaded.
        self.env['project.project'].get_view(view.id, 'list')

    def test_the_dashboard_opens_for_a_pm_without_accounting_rights(self):
        """PMs have no read access to account.move in this database.

        The advance-fee column therefore has to be a denormalised selection on
        the project, resolved under sudo(). If it ever starts reading the
        invoice with the user's own rights, this test fails with AccessError -
        which is exactly what the dashboard's audience would hit.
        """
        order, project = self._make_engagement('SE98060', pm=self.pm_tax, advance=500.0)
        invoice = self._invoice(order)
        order.se_generated_on = self.now
        project.invalidate_recordset()

        with self.assertRaises(AccessError):
            invoice.with_user(self.pm_tax).read(['amount_residual'])

        as_pm = project.with_user(self.pm_tax)
        as_pm.invalidate_recordset()
        self.assertEqual(as_pm.read([
            'engagement_letter_sent',
            'engagement_letter_signed',
            'engagement_letter_signed_date',
            'advance_invoice_status',
            'date_start',
            'user_id',
            'department_id',
            'engagement_status',
        ])[0]['advance_invoice_status'], 'posted')

        # ...and searching the dashboard as that PM works too.
        self.assertEqual(
            self.Project.with_user(self.pm_tax).search([
                ('id', '=', project.id), ('engagement_status', '=', 'awaiting_signature')]),
            project,
        )

    def test_the_invoice_link_stays_behind_the_accounting_group(self):
        """advance_invoice_status is for everyone; the invoice itself is not."""
        _order, project = self._make_engagement('SE98061', pm=self.pm_tax, advance=500.0)
        with self.assertRaises(AccessError):
            project.with_user(self.pm_tax).read(['advance_invoice_id'])
