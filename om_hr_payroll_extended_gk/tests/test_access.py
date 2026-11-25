from datetime import date

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import CountryPayrollCase


@tagged('post_install', '-at_install', 'country_payroll')
class TestCountryAndAccess(CountryPayrollCase):
    """A. Country & company, B. Payroll Officer, I. regression of existing rules."""

    def test_a1_companies_from_leave_location_contracts(self):
        """Options = companies on the contracts of users whose leave location is the payroll's."""
        india = self.cfg_in._country_companies(date(2039, 2, 26), date(2039, 3, 25))
        ae = self.cfg_ae._country_companies(date(2039, 2, 26), date(2039, 3, 25))
        self.assertIn(self.co_in, india)
        self.assertIn(self.co_ae, ae)
        self.assertFalse(india.filtered(lambda c: c.partner_id.country_id.code != 'IN'))
        self.assertFalse(ae.filtered(lambda c: c.partner_id.country_id.code != 'AE'))
        # a Dubai-leave employee on an India company contract does not add it to India Payroll...
        spare_in = self.env['res.company'].search([('partner_id.country_id.code', '=', 'IN'),
                                                   ('id', 'not in', india.ids)], limit=1)
        if spare_in:
            self._employee('PC Dubai On India Co', 'dubai', spare_in, wage=1000)
            self.assertNotIn(spare_in, self.cfg_in._country_companies(date(2039, 2, 26), date(2039, 3, 25)))
            # ...an India-leave one does
            self._employee('PC India On India Co', 'india', spare_in, wage=1000)
            self.assertIn(spare_in, self.cfg_in._country_companies(date(2039, 2, 26), date(2039, 3, 25)))

    def test_a2_default_companies_follow_period(self):
        batch = self.Batch.with_user(self.officer_in).create(
            {'payroll_country_id': self.cfg_in.id, 'month': '3', 'year': '2039'})
        self.assertEqual(batch.sudo().company_ids,
                         self.cfg_in._country_companies(batch.date_from, batch.date_to))
        self.assertIn(self.co_in, batch.sudo().company_ids)
        self.assertEqual(batch.sudo().allowed_company_ids, batch.sudo().company_ids)
        # the officer does not need the companies in Allowed Companies
        self.officer_in.company_ids = [(3, self.co_in.id)]
        batch2 = self.Batch.with_user(self.officer_in).create(
            {'payroll_country_id': self.cfg_in.id, 'month': '4', 'year': '2039'})
        self.assertIn(self.co_in, batch2.sudo().company_ids)
        self.assertTrue(batch2.with_user(self.officer_in).company_names)

    def test_a3_foreign_company_refused(self):
        with self.assertRaises(ValidationError):
            self._batch(self.cfg_in, companies=self.co_in | self.co_ae)

    def test_b1_officer_sees_own_country_only(self):
        b_ae = self._batch(self.cfg_ae)
        b_in = self._batch(self.cfg_in)
        seen_in = self.Batch.with_user(self.officer_in).search([('id', 'in', (b_ae | b_in).ids)])
        seen_ae = self.Batch.with_user(self.officer_ae).search([('id', 'in', (b_ae | b_in).ids)])
        seen_both = self.Batch.with_user(self.officer_both).search([('id', 'in', (b_ae | b_in).ids)])
        self.assertEqual(seen_in, b_in)
        self.assertEqual(seen_ae, b_ae)
        self.assertEqual(seen_both, b_ae | b_in)
        with self.assertRaises(AccessError):
            b_ae.with_user(self.officer_in).read(['name'])

    def test_b2_officer_cannot_create_other_country(self):
        with self.assertRaises(AccessError):
            self._batch(self.cfg_ae, user=self.officer_in)

    def test_b3_fetch_skips_other_leave_location(self):
        dubai_on_india = self._employee('PC Dubai Leave India Co', 'dubai', self.co_in, wage=1000)
        batch = self._batch(self.cfg_in)
        with self.fake_attendance():
            batch.action_fetch_employees()
        self.assertNotIn(dubai_on_india, batch.sudo().line_ids.employee_id)
        reasons = {x.employee_id: x.reason for x in batch.sudo().excluded_ids}
        self.assertIn('Leave location is Dubai', reasons[dubai_on_india])

    def test_b4_lines_follow_country_rules(self):
        batch = self._calculated(self.cfg_in)
        Line = self.env['payroll.country.line']
        self.assertTrue(Line.with_user(self.officer_in).search([('batch_id', '=', batch.id)]))
        self.assertFalse(Line.with_user(self.officer_ae).search([('batch_id', '=', batch.id)]))
        self.assertFalse(Line.with_user(self.stranger).search([('batch_id', '=', batch.id)]))
        with self.assertRaises(AccessError):
            batch.with_user(self.officer_ae).action_calculate()

    def test_b5_menus_follow_countries(self):
        Menu = self.env['ir.ui.menu']
        menus_in = Menu.with_user(self.officer_in).load_menus(False)
        menus_both = Menu.with_user(self.officer_both).load_menus(False)
        menus_emp = Menu.with_user(self.stranger).load_menus(False)
        self.assertIn(self.cfg_in.menu_id.id, menus_in)
        self.assertNotIn(self.cfg_ae.menu_id.id, menus_in)
        self.assertIn(self.cfg_ae.menu_id.id, menus_both)
        self.assertIn(self.cfg_in.menu_id.id, menus_both)
        self.assertNotIn(self.cfg_in.menu_id.id, menus_emp)
        my = self.env.ref('om_hr_payroll_extended_gk.menu_my_payslips')
        self.assertIn(my.id, menus_emp, "every internal user gets My Payslips")
        app = self.env.ref('om_hr_payroll_extended_gk.menu_payslip_app_root')
        self.assertEqual(my.parent_id, app, "My Payslips lives in its own Payslip app")
        self.assertFalse(app.parent_id)
        self.assertIn(app.id, menus_emp)
        self.assertIn(app.id, menus_emp['root']['children'], "Payslip is a top-level app")
        approvals = self.env.ref('om_hr_payroll_extended_gk.menu_payroll_approvals')
        self.assertNotIn(approvals.id, menus_emp)
        self.assertNotIn(approvals.id, menus_in, "Payroll Approvals: Payroll Admins only")
        self.assertIn(approvals.id, Menu.with_user(self.approver).load_menus(False))
        # the Officer's country follows their Leave Location at once
        self.officer_in.country = 'dubai'
        menus_moved = Menu.with_user(self.officer_in).load_menus(False)
        self.assertIn(self.cfg_ae.menu_id.id, menus_moved)
        self.assertNotIn(self.cfg_in.menu_id.id, menus_moved)

    def test_b7_officer_employees_and_contracts_follow_leave_location(self):
        Employee = self.env['hr.employee']
        Contract = self.env['hr.contract']
        ids = (self.emp_in | self.emp_ae).ids
        seen = Employee.with_user(self.officer_in).search([('id', 'in', ids)])
        self.assertEqual(seen, self.emp_in, "India officer: India employees only")
        self.assertEqual(Contract.with_user(self.officer_in).search([('employee_id', 'in', ids)]),
                         self.emp_in.contract_ids)
        with self.assertRaises(AccessError):
            self.emp_ae.with_user(self.officer_in).read(['name'])
        self.assertEqual(Employee.with_user(self.officer_ae).search([('id', 'in', ids)]), self.emp_ae)
        # Managers / Admins see every employee
        self.assertEqual(Employee.with_user(self.payroll_admin).search([('id', 'in', ids)]), self.emp_in | self.emp_ae)
        self.assertEqual(Employee.with_user(self.approver).search([('id', 'in', ids)]), self.emp_in | self.emp_ae)
        # an HR Administrator who is also a Payroll Officer is not limited
        hr_admin = self.officer_in.copy({'login': 'pc_hr_admin_officer'})
        hr_admin.write({'country': 'india', 'groups_id': [(4, self.env.ref('hr.group_hr_manager').id)]})
        self.assertEqual(Employee.with_user(hr_admin).search([('id', 'in', ids)]), self.emp_in | self.emp_ae)
        # a new Leave Location applies at once
        self.officer_in.country = 'dubai'
        self.assertEqual(Employee.with_user(self.officer_in).search([('id', 'in', ids)]), self.emp_ae)

    def test_b6_new_country_gets_menu(self):
        cfg = self.env['payroll.country'].create({'name': 'Oman Payroll', 'country_id': self.env.ref('base.om').id})
        self.assertTrue(cfg.menu_id and cfg.action_id)
        self.assertEqual(cfg.menu_id.parent_id, self.env.ref('om_hr_payroll.menu_hr_payroll_root'))

    def test_i1_existing_payroll_officer_rule_unchanged(self):
        """Group rules are OR-ed: the self-service rule must not shrink Payroll's own officer access."""
        om_officer = self.officer_ae
        slip = self.env['hr.payslip'].create({
            'employee_id': self.emp_ae.id, 'contract_id': self.emp_ae.contract_ids[:1].id,
            'struct_id': self.structure.id, 'date_from': '2039-02-26', 'date_to': '2039-03-25',
            'name': 'regression'})
        # employee without department -> Payroll's officer rule shows it
        self.assertTrue(self.env['hr.payslip'].with_user(om_officer).search([('id', '=', slip.id)]))
        # a plain employee does not see a draft payslip, not even their own
        self.assertFalse(self.env['hr.payslip'].with_user(self.emp_ae.user_id).search([('id', '=', slip.id)]))

    def test_i2_plain_payslip_compute_unchanged(self):
        """A payslip made the usual Payroll way still computes with the same rules."""
        with self.fake_attendance():
            Payslip = self.env['hr.payslip']
            contract = self.emp_ae.contract_ids[:1]
            vals = Payslip.with_context(contract=True).onchange_employee_id(
                '2039-02-26', '2039-03-25', self.emp_ae.id, contract.id)['value']
            slip = Payslip.create(dict(employee_id=self.emp_ae.id, date_from='2039-02-26', date_to='2039-03-25',
                                       contract_id=contract.id, struct_id=vals['struct_id'], name=vals['name'],
                                       worked_days_line_ids=[(0, 0, w) for w in vals['worked_days_line_ids']]))
            slip.compute_sheet()
        net = slip.line_ids.filtered(lambda l: l.code == 'NET').total
        self.assertAlmostEqual(net, 10000.0, places=2)
        self.assertFalse(slip.country_line_id)

    def test_b8_employees_and_contracts_menus_list_active_users_only(self):
        """Employees / Contracts menus: only employees whose user is active (display only)."""
        emp_action = self.env.ref('hr.open_view_employee_list_my')
        con_action = self.env.ref('hr_contract.action_hr_contract')
        self.assertIn("('user_id.active', '=', True)", emp_action.domain)
        self.assertIn("('employee_id.user_id.active', '=', True)", con_action.domain)
        self.emp_ae2.user_id.active = False
        domain = [('id', 'in', (self.emp_ae | self.emp_ae2).ids), ('user_id.active', '=', True)]
        self.assertEqual(self.env['hr.employee'].search(domain), self.emp_ae)
        self.assertEqual(self.env['hr.contract'].search([('employee_id', 'in', (self.emp_ae | self.emp_ae2).ids),
                                                         ('employee_id.user_id.active', '=', True)]),
                         self.emp_ae.contract_ids)
        # an archived user's contract is archived and the employee is not in payroll
        self.assertFalse(self.emp_ae2.with_context(active_test=False).contract_ids.filtered('active'))
        batch = self._calculated(self.cfg_ae)
        self.assertNotIn(self.emp_ae2, batch.sudo().line_ids.employee_id)

    def test_b9_archiving_a_user_takes_the_employee_out_of_open_payroll(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae2)
        contract = line.contract_id
        self.emp_ae2.user_id.action_archive()
        self.assertFalse(line.exists(), "removed from the open batch")
        self.assertFalse(contract.active, "contract archived")
        self.assertIn(self.emp_ae2, batch.sudo().excluded_ids.employee_id)
        self.assertTrue(self.emp_ae2.active, "the employee itself stays active")
        # the other employee is untouched
        self.assertTrue(self._line(batch, self.emp_ae))
        # an employee without a user is never fetched either
        nouser = self._employee('PC No User', 'dubai', self.co_ae, wage=1000)
        nouser.user_id = False
        eligible, excluded = self._batch(self.cfg_ae, companies=self.co_ae)._eligible_contracts()
        self.assertNotIn(nouser, eligible)
        self.assertIn(nouser, [emp for emp, _c, _r in excluded])
