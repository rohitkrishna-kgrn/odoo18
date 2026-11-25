from datetime import date, datetime

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import PERIOD_FROM, PERIOD_TO, CountryPayrollCase


@tagged('post_install', '-at_install', 'country_payroll')
class TestFetchAndCalculation(CountryPayrollCase):
    """C. Employee & contract, D. attendance & leave, E. salary."""

    # ---------------------------------------------------------------- C
    def test_c1_fetch_eligible_and_excluded(self):
        draft = self._employee('PC Draft Contract', 'dubai', self.co_ae, wage=5000, contract_state='draft')
        ended = self._employee('PC Ended Before', 'dubai', self.co_ae, wage=5000,
                               contract_end=date(2039, 1, 31), contract_state='close')
        batch = self._batch(self.cfg_ae)
        with self.fake_attendance():
            batch.action_fetch_employees()
        employees = batch.sudo().line_ids.employee_id
        self.assertIn(self.emp_ae, employees)
        self.assertIn(self.emp_ae2, employees)
        self.assertNotIn(self.emp_in, employees, "India contract is not in a UAE company")
        self.assertNotIn(draft, employees)
        self.assertNotIn(ended, employees, "contract ended before the period")
        reasons = {x.employee_id: x.reason for x in batch.sudo().excluded_ids}
        self.assertIn('not started', reasons[draft])
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.contract_ref, 'Contract PC Dubai One')
        self.assertEqual(line.company_id, self.co_ae)
        self.assertEqual(line.employee_name, 'PC Dubai One')
        self.assertEqual(line.contract_wage, 10000)

    def test_c2_joiner_and_leaver_mid_month(self):
        joiner = self._employee('PC Joiner', 'dubai', self.co_ae, wage=2800, basic_salary=2800,
                                contract_start=date(2039, 3, 12))
        leaver = self._employee('PC Leaver', 'dubai', self.co_ae, wage=2800, basic_salary=2800,
                                contract_end=date(2039, 3, 11), contract_state='close')
        batch = self._batch(self.cfg_ae)
        self.worked_overrides = {joiner.id: {'present': 0.0}, leaver.id: {'present': 0.0}}
        with self.fake_attendance():
            batch.action_fetch_employees()
            batch.action_calculate()
        j = self._line(batch, joiner)
        lv = self._line(batch, leaver)
        self.assertEqual(j.window_from, date(2039, 3, 12))
        self.assertEqual(lv.window_to, date(2039, 3, 11))
        self.assertEqual(j.out_of_contract_days, 14)     # 26 Feb - 11 Mar
        self.assertEqual(lv.out_of_contract_days, 14)    # 12 Mar - 25 Mar
        # no attendance: the 12 working days INSIDE the contract are absent, but absent days
        # are not LOP (only late logins + unpaid leave); days outside the contract never deduct
        self.assertEqual(j.weekly_off_days, 2.0)
        self.assertEqual(lv.weekly_off_days, 2.0)
        self.assertEqual((j.absent_days, j.lop_days), (12.0, 0.0))
        self.assertEqual((lv.absent_days, lv.lop_days), (12.0, 0.0))
        self.assertAlmostEqual(j.net, 2800, places=2)
        self.assertEqual(j.payslip_id.lop_days, 0.0)

    def test_c3_duplicate_period_refused(self):
        first = self._calculated(self.cfg_ae)
        second = self._batch(self.cfg_ae)
        with self.fake_attendance():
            second.action_fetch_employees()
        self.assertNotIn(self.emp_ae, second.sudo().line_ids.employee_id)
        reasons = {x.employee_id: x.reason for x in second.sudo().excluded_ids}
        self.assertIn(first.name, reasons[self.emp_ae])
        # after cancelling the first batch the period can be payrolled again
        first.action_cancel()
        with self.fake_attendance():
            second.action_fetch_employees()
        self.assertIn(self.emp_ae, second.sudo().line_ids.employee_id)

    def test_c4_paid_month_matched_by_end_date(self):
        """Old calendar payslips: 1-28 Feb is February even though it overlaps the
        March period (26 Feb - 25 Mar); 1-31 Mar is March and blocks the fetch."""
        Payslip = self.env['hr.payslip']
        contract = self.emp_ae.contract_ids[:1]
        feb = Payslip.create({'employee_id': self.emp_ae.id, 'contract_id': contract.id, 'name': 'old feb',
                              'struct_id': self.structure.id, 'date_from': '2039-02-01', 'date_to': '2039-02-28'})
        feb.write({'state': 'done'})
        batch = self._batch(self.cfg_ae)
        with self.fake_attendance():
            batch.action_fetch_employees()
        line = self._line(batch, self.emp_ae)
        self.assertTrue(line, "February's payslip does not block March")
        self.assertNotIn('already has payslip', line.validation_message or '')
        mar = Payslip.create({'employee_id': self.emp_ae2.id, 'contract_id': self.emp_ae2.contract_ids[:1].id,
                              'name': 'old mar', 'struct_id': self.structure.id,
                              'date_from': '2039-03-01', 'date_to': '2039-03-31'})
        mar.write({'state': 'done'})
        with self.fake_attendance():
            batch.action_fetch_employees()
        self.assertNotIn(self.emp_ae2, batch.sudo().line_ids.employee_id)
        reasons = {x.employee_id: x.reason for x in batch.sudo().excluded_ids}
        self.assertIn('Already paid', reasons[self.emp_ae2])

    # ---------------------------------------------------------------- D
    def _leave(self, employee, ltype, start, end=None, state='approved', half=False):
        return self.env['leave.request'].create({
            'user_id': employee.user_id.id, 'leave_type_id': ltype.id, 'start_date': start,
            'end_date': end or start, 'is_half_day': half, 'state': state, 'reason': 'test'})

    def test_d1_leave_classification(self):
        LeaveType = self.env['leave.type']
        paid_type = LeaveType.search([('is_permission', '=', False), ('sick_pay_tier', '=', False),
                                      ('id', '!=', self.env.ref('leave_management_rk.leave_type_lop').id)], limit=1)
        lop_type = self.env.ref('leave_management_rk.leave_type_lop')
        # 2-3 Mar 2039 = Wed-Thu, 7 Mar = Mon, 8 Mar = Tue
        self._leave(self.emp_in, paid_type, date(2039, 3, 2), date(2039, 3, 3))
        self._leave(self.emp_in, lop_type, date(2039, 3, 7))
        self._leave(self.emp_in, paid_type, date(2039, 3, 8), half=True)
        self._leave(self.emp_in, paid_type, date(2039, 3, 9), state='rejected')
        self._leave(self.emp_in, paid_type, date(2039, 3, 10), state='cancelled')
        self._leave(self.emp_in, paid_type, date(2039, 3, 14), state='waiting_manager')
        batch = self._batch(self.cfg_in)
        batch.action_fetch_employees()          # real Payroll worked days
        line = self._line(batch, self.emp_in)
        treatments = {(d.date_from, d.treatment): d.days_in_period for d in line.leave_detail_ids}
        self.assertEqual(treatments[(date(2039, 3, 2), 'paid')], 2.0)
        self.assertEqual(treatments[(date(2039, 3, 7), 'unpaid')], 1.0)
        self.assertEqual(treatments[(date(2039, 3, 8), 'paid')], 0.5)
        self.assertEqual(len(line.leave_detail_ids), 3, "rejected / cancelled / pending leave never counts")
        self.assertEqual(line.unpaid_leave_days, 1.0)
        self.assertEqual(line.paid_leave_days, 2.5)
        self.assertEqual(line.half_days, 1.0)
        self.assertEqual(line.pending_leave_count, 1)
        self.assertIn('awaiting approval', line.validation_message)

    def test_d2_attendance_present_absent(self):
        Attendance = self.env['hr.attendance']
        # newest first: attendance_extended_rk checks earlier days of the month
        for day in (7, 3, 2):
            Attendance.create({
                'employee_id': self.emp_ae.id,
                'check_in': datetime(2039, 3, day, 4, 0), 'check_out': datetime(2039, 3, day, 12, 0),
                'in_latitude': 25.2, 'in_longitude': 55.3, 'out_latitude': 25.2, 'out_longitude': 55.3,
            })
        batch = self._batch(self.cfg_ae)
        batch.action_fetch_employees()
        line = self._line(batch, self.emp_ae)
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        self.assertEqual(line.total_days, days)
        self.assertEqual(line.present_days, 3.0)
        self.assertEqual(line.weekly_off_days, 4.0)
        self.assertEqual(line.working_days, days - 4)
        self.assertEqual(line.absent_days, days - 4 - 3)
        self.assertEqual(line.calc_lop_days, line.late_deduct_days + line.unpaid_leave_days,
                         "absent days are not LOP: only late logins + unpaid leave")
        self.assertGreater(line.worked_hours, 0)

    def test_d3_public_holiday_and_weekly_off_not_lop(self):
        self.env['public.holiday'].create({'name': 'PC Holiday', 'date': date(2039, 3, 1)})
        self.worked_overrides = {}
        batch = self._batch(self.cfg_ae)
        batch.action_fetch_employees()              # real engine: no attendance
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.public_holidays, 1.0)
        self.assertEqual(line.absent_days, line.total_days - 4 - 1)
        self.assertEqual(line.calc_lop_days, line.late_deduct_days + line.unpaid_leave_days)

    # ---------------------------------------------------------------- E
    def test_e1_uae_salary_uses_payroll_rules(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.state, 'calculated')
        self.assertTrue(line.payslip_id)
        self.assertEqual(line.payslip_id.country_line_id, line)
        self.assertEqual(line.payslip_id.company_id, self.co_ae)
        self.assertEqual((line.basic, line.hra, line.other_allowances), (6000, 3000, 1000))
        self.assertEqual(line.gross, 10000)
        self.assertEqual(line.epf, 0, "no EPF outside India")
        self.assertEqual(line.net, 10000)
        net_line = line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET')
        self.assertAlmostEqual(net_line.total, line.net, places=2)

    def test_e2_india_epf_contract_basic(self):
        batch = self._calculated(self.cfg_in)
        line = self._line(batch, self.emp_in)
        self.assertTrue(line.pf_india)
        self.assertEqual(line.basic, 20000, "Salary After LOP >= 25,000 -> contract Basic")
        self.assertEqual(line.epf, 0, "EPF is manual entry only")
        self.assertEqual(line.gross, 40000, "India gross = wage")
        self.assertEqual(line.net, 40000)

    def test_e3_india_epf_percent_basic(self):
        batch = self._calculated(self.cfg_in)
        line = self._line(batch, self.emp_in_low)
        self.assertEqual(line.basic, 14000, "below threshold -> 70% of Salary After LOP")
        self.assertEqual(line.epf, 0)
        self.assertEqual(line.net, 20000)

    def test_e4_absent_days_not_deducted(self):
        self.worked_overrides = {self.emp_ae.id: {'present': 20.0}}     # 24 working days, 4 absent
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        self.assertEqual((line.absent_days, line.lop_days, line.lop_amount), (4.0, 0.0, 0.0))
        self.assertEqual(line.payslip_id.lop_days, 0.0)
        self.assertAlmostEqual(line.net, 10000, places=2)

    def test_e4b_lop_is_late_login_plus_unpaid_leave(self):
        """LOP Days = Late Login Days + approved Unpaid Leave; absent days never deduct."""
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        # 4 absent days + 3 late-login deduction days: only the 3 late-login days are LOP
        self.worked_overrides = {self.emp_ae.id: {'present': 20.0, 'late': 3.0}}
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        self.assertEqual((line.absent_days, line.late_deduct_days), (4.0, 3.0))
        self.assertEqual((line.calc_lop_days, line.lop_days), (3.0, 3.0))
        self.assertEqual(line.payslip_id.lop_days, 3.0)
        self.assertAlmostEqual(line.lop_amount, round(10000 / days * 3, 2), places=2)
        self.assertAlmostEqual(line.net, 10000 - line.lop_amount, places=2)
        # late logins with full attendance are LOP too
        self.worked_overrides = {self.emp_ae2.id: {'late': 2.5}}
        with self.fake_attendance():
            batch.action_fetch_employees()
            batch.action_calculate()
        line2 = self._line(batch, self.emp_ae2)
        self.assertEqual((line2.absent_days, line2.lop_days, line2.payslip_id.lop_days), (0.0, 2.5, 2.5))
        # approved unpaid (LOP-type) leave is LOP, paid leave is not
        lop_type = self.env.ref('leave_management_rk.leave_type_lop')
        self._leave(self.emp_in, lop_type, date(2039, 3, 7))          # Monday
        self.worked_overrides = {self.emp_in.id: {'present': 22.0}}   # 2 days not present: 1 leave + 1 absent
        batch_in = self._calculated(self.cfg_in)
        line_in = self._line(batch_in, self.emp_in).with_user(self.officer_in)
        self.assertEqual((line_in.unpaid_leave_days, line_in.absent_days, line_in.lop_days), (1.0, 2.0, 1.0),
                         "only the unpaid leave day is LOP, the plain absence is not")
        self.assertAlmostEqual(line_in.lop_amount, round(40000 / days * 1, 2), places=2)
        with self.fake_attendance():
            # typed absent days do not move LOP
            line_in.write({'absent_days': 5.0})
            self.assertEqual((line_in.lop_days, line_in.payslip_id.lop_days), (1.0, 1.0))
            # typed late login / unpaid leave do, with the on-screen LOP Days (onchange) not marked as typed
            line_in.write({'late_deduct_days': 1.5, 'lop_days': 2.5})
            self.assertNotIn('lop_days', line_in.manual_keys)
            self.assertEqual((line_in.lop_days, line_in.payslip_id.lop_days), (2.5, 2.5))
            self.assertAlmostEqual(line_in.lop_amount, round(40000 / days * 2.5, 2), places=2)
            # LOP Days typed 0 -> no deduction; the on-screen LOP Deduction preview is not a typed amount
            line_in.write({'lop_days': 0.0, 'lop_amount': line_in._lop_amount_preview(0.0)})
            self.assertNotIn('lop_amount', line_in.manual_keys)
            self.assertEqual((line_in.lop_days, line_in.lop_amount, line_in.payslip_id.lop_days), (0.0, 0.0, 0.0))

    def test_e4c_onchange_previews_lop(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        self.assertAlmostEqual(line._lop_amount_preview(2.0), round(10000 / days * 2, 2), places=2)
        new = self.env['payroll.country.line'].new({'contract_wage': 10000.0, 'total_days': days,
                                                    'late_deduct_days': 1.0, 'unpaid_leave_days': 0.0})
        new.unpaid_leave_days = 2.0
        new._onchange_lop_sources()
        self.assertEqual(new.lop_days, 3.0)
        new._onchange_lop_days()
        self.assertAlmostEqual(new.lop_amount, round(10000 / days * 3, 2), places=2)
        new.absent_days = 6.0
        new._onchange_absent_days()
        self.assertEqual(new.lop_days, 3.0, "absent days do not change LOP")

    def test_e5_manual_edit_recalculates_and_audits(self):
        batch = self._calculated(self.cfg_in)
        line = self._line(batch, self.emp_in).with_user(self.officer_in)
        with self.fake_attendance():
            line.write({'basic': 22000.0})
        line = line.sudo()
        self.assertIn('basic', line.manual_keys)
        self.assertEqual(line.basic, 22000)
        self.assertEqual(line.epf, 0, "EPF does not follow Basic: manual entry only")
        self.assertEqual(line.calc_basic, 20000)
        log = line.change_log_ids.filtered(lambda l: l.field_name == 'basic')
        self.assertEqual((log.old_value, log.new_value, log.user_id), ('20000.00', '22000.00', self.officer_in))
        net_line = line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET')
        self.assertAlmostEqual(net_line.total, line.net, places=2)
        self.assertAlmostEqual(line.gross, line.basic + line.hra + line.other_allowances, places=2)
        # recalculation keeps the manual value, other figures follow the rules
        with self.fake_attendance():
            batch.action_recalculate()
        self.assertEqual(line.basic, 22000)
        # typed deduction + reset
        with self.fake_attendance():
            line.with_user(self.officer_in).write({'other_deductions': 500.0})
            self.assertAlmostEqual(line.net, line.gross - line.epf - 500, places=2)
            line.with_user(self.officer_in).action_reset_manual()
        self.assertEqual(line.basic, 20000)
        self.assertEqual(line.other_deductions, 0)
        self.assertFalse(line.has_manual)

    def test_e6_manual_lop_days_go_through_engine(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        with self.fake_attendance():
            line.with_user(self.officer_ae).write({'lop_days': 2.0})
        self.assertEqual(line.lop_days, 2.0)
        self.assertEqual(line.payslip_id.lop_days, 2.0)
        self.assertAlmostEqual(line.lop_amount, round(10000 / days * 2, 2), places=2)
        with self.fake_attendance():
            line.with_user(self.officer_ae).write({'overtime_amount': 300.0})
        self.assertAlmostEqual(line.gross, 10300, places=2)
        self.assertTrue(line.payslip_id.line_ids.filtered(lambda l: l.code == 'PAYROLL_OT'))

    def test_e8_every_popup_field_editable_and_feeds_pay(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        officer_line = line.with_user(self.officer_ae)
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        contract = self.emp_ae.contract_ids[:1]
        with self.fake_attendance():
            # attendance: absences move present days but are not LOP
            officer_line.write({'absent_days': 3.0})
            self.assertEqual(line.present_days, 21.0)
            self.assertEqual(line.lop_days, 0.0)
            # late login days typed: 3 LOP days through the Payroll LOP rule
            officer_line.write({'late_deduct_days': 3.0})
            self.assertEqual(line.lop_days, 3.0)
            self.assertAlmostEqual(line.lop_amount, round(10000 / days * 3, 2), places=2)
            # contract wage typed: saved on the contract too, the rules use it
            officer_line.write({'contract_wage': 12000.0, 'contract_basic': 7000.0})
            self.assertEqual(line.basic, 7000.0)
            self.assertAlmostEqual(line.lop_amount, round(12000 / days * 3, 2), places=2)
            self.assertEqual((contract.wage, contract.basic_salary), (12000, 7000))
            # any contract component typed on the line goes to the contract the same way
            self.assertEqual(line.contract_hra, 3000.0)
            officer_line.write({'contract_hra': 3500.0, 'contract_other_deduction': 200.0})
            self.assertEqual(line.hra, 3500.0)
            self.assertEqual(line.other_deductions, 200.0)
            self.assertEqual((contract.hra, contract.other_deduction), (3500, 200))
            self.assertNotIn('contract_wage', line.manual_keys, "a synced value is not a manual override")
            # LOP deduction typed as an amount
            officer_line.write({'lop_amount': 100.0})
            self.assertEqual(line.lop_amount, 100.0)
            net_line = line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET')
            self.assertAlmostEqual(net_line.total, line.net, places=2)
            # employee + bank values: saved on the employee too and re-checked
            iban = self.emp_ae.bank_iban_number
            self.env['hr.department'].create({'name': 'Audit'})
            officer_line.write({'employee_name': 'PC Dubai One (typed)', 'department_name': 'audit',
                                'bank_iban': 'AE00BAD', 'work_email': 'typed@example.com'})
            self.assertEqual(line.bank_iban, 'AE00BAD')
            self.assertEqual((self.emp_ae.name, self.emp_ae.department_id.name, self.emp_ae.bank_iban_number,
                              self.emp_ae.work_email),
                             ('PC Dubai One (typed)', 'Audit', 'AE00BAD', 'typed@example.com'))
            self.assertEqual(line.department_name, 'Audit', "shown as the department is named")
            officer_line.write({'bank_iban': iban})
            self.assertEqual((line.bank_iban, self.emp_ae.bank_iban_number), (iban, iban))
            # re-fetch / recalculate keep every typed value
            batch.action_fetch_employees()
            batch.action_calculate()
            self.assertEqual((line.employee_name, line.department_name, line.present_days, line.basic),
                             ('PC Dubai One (typed)', 'Audit', 21.0, 7000.0))
            labels = set(line.change_log_ids.mapped('field_name'))
            self.assertTrue({'absent_days', 'late_deduct_days', 'contract_wage', 'lop_amount', 'employee_name',
                             'bank_iban'} <= labels)
            # approved leave lines can be edited too
            officer_line.write({'leave_detail_ids': [(0, 0, {'leave_type': 'Typed', 'days_in_period': 1,
                                                             'treatment': 'paid'})]})
            self.assertIn('leave_detail_ids', line.manual_keys)
            # back to the source / calculated values
            officer_line.action_reset_manual()
        # attendance / leave / figures go back; employee + contract values are the records' own now
        self.assertEqual((line.employee_name, line.present_days, line.basic, line.lop_days),
                         ('PC Dubai One (typed)', 24.0, 7000.0, 0.0))
        self.assertEqual((line.contract_hra, line.hra, line.contract_other_deduction), (3500.0, 3500.0, 200.0))
        self.assertFalse(line.leave_detail_ids)
        with self.assertRaises(UserError):
            officer_line.write({'net': 1.0})

    def test_e9_absent_present_live_onchange(self):
        from odoo.tests import Form
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        self.assertEqual((line.working_days, line.present_days, line.absent_days), (24.0, 24.0, 0.0))
        with self.fake_attendance(), Form(line.with_user(self.officer_ae),
                                          view='om_hr_payroll_extended_gk.view_payroll_country_line_form') as f:
            f.absent_days = 4.0
            self.assertEqual(f.present_days, 20.0, "present follows absent on screen")
            self.assertEqual(f.lop_days, 0.0, "absent days are not LOP")
            f.present_days = 22.0
            self.assertEqual(f.absent_days, 2.0, "absent follows present on screen")
            f.working_days = 25.0
            self.assertEqual(f.absent_days, 3.0)
            f.late_deduct_days = 1.5
            self.assertEqual(f.lop_days, 1.5, "LOP Days follows Late Login + Unpaid Leave on screen")
            self.assertAlmostEqual(f.lop_amount, round(10000 / 28 * 1.5, 2), places=2,
                                   msg="LOP Deduction follows LOP Days on screen")
            f.lop_days = 0.0
            self.assertEqual(f.lop_amount, 0.0, "LOP Days 0 -> no LOP Deduction on screen")
            f.lop_days = 1.5
        self.assertEqual((line.present_days, line.absent_days), (22.0, 3.0))
        self.assertEqual(line.lop_days, 1.5, "LOP = the saved Late Login + Unpaid Leave days")
        self.assertEqual(line.payslip_id.lop_days, 1.5)
        self.assertNotIn('lop_days', line.manual_keys, "the on-screen LOP is not a typed override")
        self.assertNotIn('lop_amount', line.manual_keys, "the on-screen LOP Deduction is not a typed amount")
        self.assertAlmostEqual(line.lop_amount, round(10000 / 28 * 1.5, 2), places=2)

    def test_e10_pf_esi_salary_admin_formula_and_manual(self):
        self.assertEqual(self.cfg_in.pf_esi_mode, 'formula')
        self.assertEqual(self.cfg_ae.pf_esi_mode, 'manual')
        self.emp_in.contract_ids[:1].write({'esi_amount': 500.0, 'epf_amount': 2400.0})      # wage 40,000
        self.emp_in_low.contract_ids[:1].write({'esi_amount': 1.0, 'epf_amount': 1.0})       # wage 20,000
        batch = self._calculated(self.cfg_in)
        hi = self._line(batch, self.emp_in)
        lo = self._line(batch, self.emp_in_low)
        # PF wage = min(70% of 40,000, 25,000); ESI: 40,000 is above the 21,000 limit
        self.assertEqual((hi.pf_wage, hi.epf, hi.pf_employer, hi.esi), (25000.0, 3000.0, 3000.0, 0.0))
        # PF wage 70% of 20,000 = 14,000 -> 1,680; ESI 0.75% / 3.25% of 20,000 (rounded up)
        self.assertEqual((lo.pf_wage, lo.epf, lo.esi_wage, lo.esi, lo.esi_employer),
                         (14000.0, 1680.0, 20000.0, 150.0, 650.0))
        self.assertEqual(lo.other_deductions, 0.0, "ESI is its own column")
        self.assertEqual(lo.net, 20000 - 1680 - 150)
        codes = {l.code: l.total for l in lo.payslip_id.line_ids}
        self.assertEqual((codes['EPF'], codes['ESI']), (-1680.0, -150.0))
        self.assertAlmostEqual(codes['NET'], lo.net, places=2)
        self.assertFalse(lo.has_manual)
        # a typed amount wins, is audited and survives Recalculate
        with self.fake_attendance():
            hi.with_user(self.officer_in).write({'epf': 1800.0, 'esi': 300.0})
            self.assertEqual((hi.epf, hi.esi, hi.calc_epf), (1800.0, 300.0, 3000.0))
            self.assertEqual(hi.net, 40000 - 2100)
            batch.action_recalculate()
            self.assertEqual((hi.epf, hi.esi), (1800.0, 300.0))
            hi.with_user(self.officer_in).action_reset_manual()
            self.assertEqual((hi.epf, hi.esi), (3000.0, 0.0))
            # LOP lowers the PF wage: 4 late-login LOP days
            self.worked_overrides = {self.emp_in_low.id: {'late': 4.0}}
            batch.action_recalculate()
            days = 28
            earned = 20000 - round(20000 / days * 4, 2)
            self.assertEqual(lo.pf_wage, round(earned * 0.7))
            self.assertEqual(lo.epf, round(lo.pf_wage * 0.12))
            # per-employee choice: Manual keeps the current amounts and lets them be typed
            officer_lo = lo.with_user(self.officer_in)
            pf_before = lo.epf
            self.assertEqual(lo.pf_esi_entry, 'formula')
            officer_lo.write({'pf_esi_entry': 'manual'})
            self.assertEqual((lo.pf_esi_entry, lo.epf), ('manual', pf_before))
            officer_lo.write({'epf': 0.0, 'esi': 75.0})
            self.assertEqual((lo.epf, lo.esi), (0.0, 75.0), "manual 0 stays 0 even though the formula says more")
            batch.action_recalculate()
            self.assertEqual((lo.epf, lo.esi), (0.0, 75.0))
            # back to Formula recalculates
            officer_lo.write({'pf_esi_entry': 'formula'})
            self.assertEqual((lo.epf, lo.esi), (lo.calc_epf, lo.calc_esi))
            self.assertGreater(lo.epf, 0)
            entries = lo.change_log_ids.filtered(lambda c: c.field_name == 'pf_esi_entry')
            self.assertEqual(entries.mapped('new_value'), ['Formula', 'Manual'])
            # the country default only sets new lines
            ae_batch = self._calculated(self.cfg_ae)
        self.assertEqual(self._line(ae_batch, self.emp_ae).pf_esi_entry, 'manual')
        self.assertEqual(self._line(ae_batch, self.emp_ae).epf, 0.0)

    def test_e11_bank_dropdown_by_country_and_ifsc_code(self):
        sbi = self.env.ref('om_hr_payroll_extended_gk.bank_in_sbi')
        hdfc = self.env.ref('om_hr_payroll_extended_gk.bank_in_hdfc')
        enbd = self.env.ref('om_hr_payroll_extended_gk.bank_ae_enbd')
        india, uae = self.env.ref('base.in'), self.env.ref('base.ae')
        self.assertEqual(self.emp_in.payroll_bank_country_ids, india)
        self.assertEqual(self.emp_ae.payroll_bank_country_ids, uae)
        self.assertEqual(hdfc.ifsc_prefix, 'HDFC')
        # employee picks SBI with an HDFC IFSC: no longer flagged (bank details are not validated)
        self.emp_in.payroll_bank_id = sbi
        self.assertEqual(self.emp_in.payroll_bank_name, 'State Bank of India')
        self.emp_ae.payroll_bank_id = enbd
        batch = self._calculated(self.cfg_in)
        line = self._line(batch, self.emp_in)
        self.assertEqual((line.bank_id, line.bank_name), (sbi, 'State Bank of India'))
        self.assertNotIn('Bank', line.validation_message or '', "an IFSC of another bank is not checked")
        # picking HDFC on the payroll line: name follows, logged
        with self.fake_attendance():
            line.with_user(self.officer_in).write({'bank_id': hdfc.id})
        self.assertEqual(line.bank_name, 'HDFC Bank')
        log = line.change_log_ids.filtered(lambda c: c.field_name == 'bank_id')
        self.assertEqual((log.old_value, log.new_value), ('State Bank of India', 'HDFC Bank'))
        # the dropdown only offers banks of the payroll country
        domain = [('country', '=', line.country_id.id)]
        offered = self.env['res.bank'].search(domain)
        self.assertIn(hdfc, offered)
        self.assertNotIn(enbd, offered)
        # a missing bank can be created from the dropdown: it gets the payroll country
        Bank = self.env['res.bank'].with_user(self.officer_in).with_context(default_country=line.country_id.id)
        new_bank = Bank.name_create('PC Cooperative Bank')[0]
        new_bank = self.env['res.bank'].browse(new_bank)
        self.assertEqual(new_bank.country, india)
        with self.fake_attendance():
            line.with_user(self.officer_in).write({'bank_id': new_bank.id})
        self.assertEqual(line.bank_name, 'PC Cooperative Bank')
        hr_user = self.officer_in.copy({'login': 'pc_hr_bank'})
        hr_user.groups_id = [(4, self.env.ref('hr.group_hr_user').id)]
        emp_bank = self.env['res.bank'].with_user(hr_user).with_context(
            default_country=self.emp_ae.payroll_bank_country_id.id).create({'name': 'PC Dubai Coop'})
        self.assertEqual(emp_bank.country, uae)

    def test_e12_pre_completed_on_create_and_company_change(self):
        """Saving a new batch fetches and calculates at once; no extra clicks."""
        with self.fake_attendance():
            batch = self.Batch.with_user(self.officer_ae).create({
                'payroll_country_id': self.cfg_ae.id, 'month': '3', 'year': '2039',
                'company_ids': [(6, 0, self.co_ae.ids)]})
        self.assertEqual(batch.state, 'calculated')
        line = self._line(batch, self.emp_ae)
        self.assertEqual(line.state, 'calculated')
        self.assertEqual((line.gross, line.net), (10000.0, 10000.0))
        self.assertTrue(line.payslip_id)
        # Fetch Employees always calculates too
        with self.fake_attendance():
            batch.action_fetch_employees()
        self.assertEqual((batch.state, line.state, line.net), ('calculated', 'calculated', 10000.0))
        # changing the companies re-fetches and recalculates
        if self.co_ae2:
            with self.fake_attendance():
                batch.write({'company_ids': [(6, 0, self.co_ae2.ids)]})
            self.assertNotIn(self.emp_ae, batch.sudo().line_ids.employee_id)

    def test_e13_employee_and_contract_stay_in_sync(self):
        """Typed on the line -> Employee / Contract; changed in HR -> every open line."""
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        officer_line = line.with_user(self.officer_ae)
        contract = self.emp_ae.contract_ids[:1]
        with self.fake_attendance():
            # HR changes the contract: the open line shows it and is recalculated
            contract.write({'wage': 11000.0, 'hra': 4000.0})
            self.assertEqual((line.contract_wage, line.contract_hra, line.hra), (11000.0, 4000.0, 4000.0))
            net = line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET')
            self.assertAlmostEqual(net.total, line.net, places=2)
            # HR changes the employee and its bank details: the line follows, bank re-checked
            self.emp_ae.write({'work_email': 'hr@example.com', 'payroll_bank_holder': 'HR Holder',
                               'bank_iban_number': 'AE00BAD'})
            self.assertEqual((line.work_email, line.bank_holder, line.bank_iban),
                             ('hr@example.com', 'HR Holder', 'AE00BAD'))
            # the contract status / structure are typed by name; unknown names are refused
            officer_line.write({'contract_state': 'running'})
            self.assertEqual((contract.state, line.contract_state), ('open', 'Running'))
            with self.assertRaises(UserError):
                officer_line.write({'department_name': 'No Such Department PC'})
            with self.assertRaises(UserError):
                officer_line.write({'contract_state': 'sleeping'})
            with self.assertRaises(UserError):
                officer_line.write({'employee_name': ''})
            # the change log says where the value was saved
            officer_line.write({'contract_pt': 150.0})
            self.assertEqual(contract.pt_amount, 150.0)
            log = line.change_log_ids.filtered(lambda l: l.field_name == 'contract_pt')
            self.assertEqual(log.synced_to, 'Contract')
            # contract end moved into the period: the payable window follows
            contract.write({'date_end': date(2039, 3, 20)})
            self.assertEqual(line.window_to, date(2039, 3, 20))
            self.assertEqual(line.out_of_contract_days, 5.0)
        # a locked batch keeps its snapshot
        batch.sudo().state = 'submitted'
        self.emp_ae.write({'work_email': 'later@example.com'})
        self.assertEqual(line.work_email, 'hr@example.com')

    def test_e14_pf_esi_india_employees_only(self):
        """A Dubai employee never gets PF / ESI, even with contract EPF / ESI amounts."""
        self.emp_ae.contract_ids[:1].write({'epf_amount': 1200.0, 'esi_amount': 300.0})
        self.emp_in.contract_ids[:1].write({'epf_amount': 2400.0})
        self.cfg_ae.pf_esi_mode = 'formula'           # even a Formula default does nothing outside India
        ae = self._line(self._calculated(self.cfg_ae), self.emp_ae)
        self.assertFalse(ae.pf_esi_applies)
        self.assertEqual((ae.epf, ae.esi, ae.calc_epf, ae.calc_esi, ae.pf_wage, ae.pf_employer),
                         (0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        codes = {l.code: l.total for l in ae.payslip_id.line_ids}
        self.assertFalse(codes.get('EPF') or codes.get('ESI'), "no EPF / ESI on the Payroll payslip")
        self.assertEqual(ae.net, ae.gross - ae.total_deductions)
        self.assertEqual(ae.total_deductions, ae.lop_amount + ae.other_deductions)
        with self.fake_attendance():
            for vals in ({'epf': 100.0}, {'esi': 10.0}, {'pf_esi_entry': 'manual'}):
                with self.assertRaises(UserError):
                    ae.with_user(self.officer_ae).write(vals)
        # India employee in the India payroll: PF applies
        ind = self._line(self._calculated(self.cfg_in), self.emp_in)
        self.assertTrue(ind.pf_esi_applies)
        self.assertEqual(ind.epf, 3000.0)

    def test_c9_archived_employees_never_in_payroll(self):
        """Archived = not paid here, even when they left inside the period; archiving
        takes an employee out of every open batch at once."""
        leaver = self._employee('PC Dubai Leaver', 'dubai', self.co_ae, wage=5000, basic_salary=5000)
        leaver.write({'departure_date': PERIOD_TO, 'active': False})     # worked the whole period
        batch = self._calculated(self.cfg_ae)
        self.assertNotIn(leaver, batch.sudo().line_ids.employee_id)
        reasons = {x.employee_id: x.reason for x in batch.sudo().excluded_ids}
        self.assertEqual(reasons[leaver], 'Employee is archived')
        # an employee archived while the batch is open leaves it, draft payslip included
        line = self._line(batch, self.emp_ae2)
        slip = line.payslip_id
        self.assertTrue(slip)
        self.emp_ae2.active = False
        self.assertFalse(line.exists())
        self.assertFalse(slip.exists())
        self.assertIn(self.emp_ae2, batch.sudo().excluded_ids.employee_id)
        self.assertTrue(batch.sudo().message_ids.filtered(lambda m: 'PC Dubai Two' in (m.body or '')))
        # a submitted batch is locked: archiving does not change it
        with self.fake_attendance():
            batch.action_submit()
        self.emp_ae.active = False
        self.assertTrue(self._line(batch, self.emp_ae))

    def test_e7_system_fields_and_locked_batches(self):
        batch = self._calculated(self.cfg_ae)
        line = self._line(batch, self.emp_ae)
        with self.assertRaises(UserError):
            line.with_user(self.officer_ae).write({'gross': 1.0})
        batch.sudo().state = 'submitted'
        with self.assertRaises(UserError):
            line.with_user(self.officer_ae).write({'basic': 1.0})

    def test_e15_work_from_home_deduction_india(self):
        batch = self._calculated(self.cfg_in)
        line = self._line(batch, self.emp_in)
        officer = line.with_user(self.officer_in)
        gross, net, other = line.gross, line.net, line.other_deductions
        self.assertFalse(line.wfh_deduction)
        # 30-day basis, whatever the period length: Gross / 30 x 4% x 30
        days = (PERIOD_TO - PERIOD_FROM).days + 1
        self.assertEqual(days, 28)
        expected = round(gross / 30 * 0.04 * 30, 2)
        self.assertEqual(line._wfh_amount(30000.0), 1200.0, "the requirement's example")
        with self.fake_attendance():
            officer.write({'work_from_home': True})
        self.assertEqual(line.wfh_deduction, expected)
        self.assertEqual(line.other_deductions, other, "other deductions untouched")
        self.assertEqual(line.total_other_deductions, other + expected)
        self.assertAlmostEqual(line.net, net - expected, places=2)
        wfh_lines = line.payslip_id.line_ids.filtered(lambda l: l.code == 'PAYROLL_WFH')
        self.assertEqual((len(wfh_lines), wfh_lines.name, wfh_lines.total),
                         (1, 'Work From Home Deduction', -expected))
        self.assertAlmostEqual(line.payslip_id.line_ids.filtered(lambda l: l.code == 'NET').total, line.net, places=2)
        # recalculation: still one line, same amount
        with self.fake_attendance():
            batch.action_recalculate()
        self.assertEqual(len(line.payslip_id.line_ids.filtered(lambda l: l.code == 'PAYROLL_WFH')), 1)
        self.assertEqual(line.wfh_deduction, expected)
        # typed other deductions stay as typed, WFH comes on top
        with self.fake_attendance():
            officer.write({'other_deductions': 500.0})
            batch.action_recalculate()
        self.assertEqual((line.other_deductions, line.wfh_deduction), (500.0, expected))
        self.assertAlmostEqual(line.total_deductions, line.epf + line.esi + line.lop_amount + 500.0 + expected, places=2)
        # Gross changes -> WFH follows
        with self.fake_attendance():
            officer.write({'contract_wage': 50000.0, 'contract_basic': 25000.0})
        self.assertEqual(line.wfh_deduction, round(line.gross * 0.04, 2))
        self.assertNotEqual(line.wfh_deduction, expected)
        # unticked -> removed, other deductions still 500
        with self.fake_attendance():
            officer.write({'work_from_home': False})
        self.assertEqual((line.wfh_deduction, line.other_deductions), (0.0, 500.0))
        self.assertFalse(line.payslip_id.line_ids.filtered(lambda l: l.code == 'PAYROLL_WFH' and l.total))
        # India only
        dubai = self._line(self._calculated(self.cfg_ae), self.emp_ae)
        with self.assertRaises(UserError):
            dubai.with_user(self.officer_ae).write({'work_from_home': True})

    def test_e16_wfh_thirty_day_basis_every_month_length(self):
        line = self.env['payroll.country.line'].new({'payroll_country_id': self.cfg_in.id})
        for gross in (30000.0, 33333.0, 18750.5):
            # same amount for 28, 29, 30 and 31-day months: the period length is never used
            self.assertEqual(line._wfh_amount(gross), round(gross / 30 * 0.04 * 30, 2))
