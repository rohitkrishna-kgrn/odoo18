from datetime import date, timedelta

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestManagerHierarchy(TransactionCase):
    """Manager -> Direct -> Indirect -> Further, plus an Outsider and a second
    Manager.  Everyone is a "User: Own Documents Only" salesperson and owns one
    lead (with one logged activity) and one quotation (with one line)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_manager = cls.env.ref('crm_manager_gk.group_crm_manager')
        cls.group_own = cls.env.ref('sales_team.group_sale_salesman')
        cls.group_all = cls.env.ref('sales_team.group_sale_salesman_all_leads')
        cls.group_admin = cls.env.ref('sales_team.group_sale_manager')
        cls.partner = cls.env['res.partner'].create({'name': 'CRM Manager Test Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'CRM Manager Test Service', 'type': 'service', 'list_price': 100})
        # crm_extended_rk: an order line needs a "Dedicated Project Manager".
        cls.line_pm = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'CRM Manager Test PM', 'login': 'crm_manager_gk_pm',
            'email': 'pm@crm-manager-gk.test', 'is_dedicated_manager': True,
            'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])]})

        cls.manager, cls.manager_emp = cls._person('manager', manager_group=True)
        cls.direct, cls.direct_emp = cls._person('direct', parent=cls.manager_emp)
        cls.indirect, cls.indirect_emp = cls._person('indirect', parent=cls.direct_emp)
        cls.further, cls.further_emp = cls._person('further', parent=cls.indirect_emp)
        cls.outsider, cls.outsider_emp = cls._person('outsider')
        cls.manager2, cls.manager2_emp = cls._person('manager2', manager_group=True)

    @classmethod
    def _person(cls, key, parent=None, manager_group=False, groups=None, employee=True):
        groups = groups or (cls.env.ref('base.group_user') | cls.group_own)
        if manager_group:
            groups |= cls.group_manager
        user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': f'CRM Manager Test {key}',
            'login': f'crm_manager_gk_test_{key}',
            'email': f'{key}@crm-manager-gk.test',
            'groups_id': [(6, 0, groups.ids)],
        })
        emp = employee and cls.env['hr.employee'].create({
            'name': user.name,
            'user_id': user.id,
            'parent_id': parent.id if parent else False,
        })
        lead = cls.env['crm.lead'].create({'name': f'Lead {key}', 'user_id': user.id, 'type': 'opportunity'})
        cls.env['mail.message'].create({
            'model': 'crm.lead', 'res_id': lead.id, 'message_type': 'comment', 'body': 'Call done',
            'mail_activity_type_id': cls.env.ref('mail.mail_activity_data_call').id,
        })
        order = cls.env['sale.order'].with_context(skip_sales_team_check=True).create({
            'partner_id': cls.partner.id,
            'user_id': user.id,
            'crm_link_override': True,
            'crm_link_override_reason': 'crm_manager_gk test',
        })
        cls.env['sale.order.line'].create(cls._line_vals(order))
        return user, emp

    @classmethod
    def _line_vals(cls, order, **extra):
        today = date.today()
        return dict({
            'order_id': order.id, 'product_id': cls.product.id, 'product_uom_qty': 1,
            'price_unit': 100, 'manager_id': cls.line_pm.id, 'estimated_hours': 1,
            'engagement_start': today, 'engagement_end': today + timedelta(days=30),
            'deadline': today + timedelta(days=30),
        }, **extra)

    def _owners(self, model, as_user, field='user_id', context=None):
        """Fixture owners whose records `as_user` can see in `model`."""
        self.env.flush_all()
        records = self.env[model].with_user(as_user).with_context(**(context or {})).search(
            [(field, 'in', self._fixture_users().ids)])
        return records.sudo().mapped(field)

    def _fixture_users(self):
        # By login, so people added inside a test are included too.
        return self.env['res.users'].search([('login', '=like', 'crm_manager_gk_test_%')])

    def _order_of(self, user):
        return self.env['sale.order'].search([('user_id', '=', user.id)], limit=1)

    @property
    def branch(self):
        return self.manager | self.direct | self.indirect | self.further

    # -- Sales dropdown -----------------------------------------------------

    def test_manager_is_a_level_of_the_sales_dropdown(self):
        sales_category = self.env.ref('base.module_category_sales_sales')
        app = [entry for entry in self.env['res.groups'].get_groups_by_application()
               if entry[0] == sales_category]
        self.assertEqual(app[0][1], 'selection', "Sales must stay a dropdown, not checkboxes")
        self.assertEqual(
            app[0][2].ids,
            [self.group_own.id, self.group_manager.id, self.group_all.id, self.group_admin.id],
            "Dropdown order must be Own Documents > Manager > All Documents > Administrator")

    def test_manager_level_implies_own_documents(self):
        self.assertIn(self.group_own, self.group_manager.implied_ids)
        self.assertIn(self.group_manager, self.group_all.trans_implied_ids)
        self.assertIn(self.group_manager, self.group_admin.trans_implied_ids)
        self.assertIn(self.group_own, self.manager.groups_id)

    # -- CRM ----------------------------------------------------------------

    def test_manager_sees_every_level(self):
        self.assertEqual(self._owners('crm.lead', self.manager), self.branch)

    def test_outsider_records_stay_hidden(self):
        for model in ('crm.lead', 'crm.activity.report', 'sale.report'):
            self.assertNotIn(self.outsider, self._owners(model, self.manager), model)
        # sale.order is checked through the Services lists: refund_management_rk
        # lets every internal user read every order outside those menus.
        self.assertNotIn(self.outsider, self._owners(
            'sale.order', self.manager, context={'own_created_quotations_only': True}))
        lead = self.env['crm.lead'].search([('user_id', '=', self.outsider.id)])
        with self.assertRaises(AccessError):
            lead.with_user(self.manager).read(['name'])

    def test_normal_user_keeps_own_documents_only(self):
        # Direct has reports of their own but not the Manager level.
        for model in ('crm.lead', 'crm.activity.report', 'sale.report'):
            self.assertEqual(self._owners(model, self.direct), self.direct, model)

    def test_new_report_is_picked_up(self):
        newcomer, _emp = self._person('newcomer', parent=self.further_emp)
        self.assertIn(newcomer, self._owners('crm.lead', self.manager))

    def test_transfer_moves_the_whole_branch(self):
        self.indirect_emp.parent_id = self.manager2_emp
        self.assertEqual(self._owners('crm.lead', self.manager), self.manager | self.direct)
        self.assertEqual(
            self._owners('crm.lead', self.manager2),
            self.manager2 | self.indirect | self.further)

    def test_group_removal_drops_hierarchy(self):
        self.manager.groups_id = [(3, self.group_manager.id)]
        self.assertEqual(self._owners('crm.lead', self.manager), self.manager)
        self.assertEqual(self._owners('sale.order', self.manager,
                                      context={'own_created_quotations_only': True}), self.manager)

    def test_manager_can_edit_but_not_delete_hierarchy_records(self):
        for model in ('crm.lead', 'sale.order'):
            report_rec = self.env[model].search([('user_id', '=', self.further.id)], limit=1)
            report_rec.with_user(self.manager).write({'name': f'{model} edited by manager'})
            self.assertEqual(report_rec.name, f'{model} edited by manager')
            with self.assertRaises(AccessError):
                report_rec.with_user(self.manager).unlink()
            outsider_rec = self.env[model].search([('user_id', '=', self.outsider.id)], limit=1)
            with self.assertRaises(AccessError):
                outsider_rec.with_user(self.manager).write({'name': 'not my team'})

    def test_normal_user_cannot_edit_reports_records(self):
        lead = self.env['crm.lead'].search([('user_id', '=', self.indirect.id)], limit=1)
        with self.assertRaises(AccessError):
            lead.with_user(self.direct).write({'name': 'renamed by direct'})

    def test_manager_creates_leads_for_self_then_reassigns(self):
        Lead = self.env['crm.lead'].with_user(self.manager)
        with self.assertRaises(AccessError):
            Lead.create({'name': 'Direct create for a report', 'user_id': self.direct.id})
        lead = Lead.create({'name': 'Created by manager', 'user_id': self.manager.id})
        lead.write({'user_id': self.direct.id})
        self.assertEqual(lead.sudo().user_id, self.direct)

    def test_activity_analysis_follows_hierarchy(self):
        self.assertEqual(self._owners('crm.activity.report', self.manager), self.branch)

    # -- Services -----------------------------------------------------------

    def test_services_lists_follow_hierarchy(self):
        ctx = {'own_created_quotations_only': True}
        self.assertEqual(self._owners('sale.order', self.manager, context=ctx), self.branch)
        self.assertEqual(self._owners('sale.order', self.direct, context=ctx), self.direct)

    def test_all_documents_user_lists_are_unchanged(self):
        all_docs, _emp = self._person('alldocs', groups=self.env.ref('base.group_user') | self.group_all)
        ctx = {'own_created_quotations_only': True}
        self.assertEqual(self._owners('sale.order', all_docs, context=ctx), self._fixture_users())
        self.assertEqual(self._owners('crm.lead', all_docs), self._fixture_users())

    def test_order_lines_of_reports_can_be_added_edited_removed(self):
        order = self._order_of(self.further)
        self.assertTrue(order.with_user(self.manager).order_line, "The report's order opens with its lines")
        new_line = self.env['sale.order.line'].with_user(self.manager).create(
            self._line_vals(order, name='Added by manager'))
        new_line.write({'name': 'Edited by manager'})
        new_line.unlink()
        outsider_line = self._order_of(self.outsider).order_line[:1]
        with self.assertRaises(AccessError):
            outsider_line.with_user(self.manager).write({'name': 'not my team'})

    def test_sales_analysis_follows_hierarchy(self):
        self.assertEqual(self._owners('sale.report', self.manager), self.branch)

    # -- hierarchy edge cases ----------------------------------------------

    def test_manager_without_employee_sees_own_only(self):
        loner, _emp = self._person('loner', manager_group=True, employee=False)
        self.assertEqual(self._owners('crm.lead', loner), loner)
        self.assertEqual(self._owners('sale.order', loner,
                                      context={'own_created_quotations_only': True}), loner)

    def test_reporting_loop_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.manager_emp.parent_id = self.further_emp       # indirect loop
        with self.assertRaises(ValidationError):
            self.direct_emp.parent_id = self.direct_emp         # self-management
        self.indirect_emp.parent_id = False                     # breaking a line is fine
        self.assertNotIn(self.further, self._owners('crm.lead', self.manager))
