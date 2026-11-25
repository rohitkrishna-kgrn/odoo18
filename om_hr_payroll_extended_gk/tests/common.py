from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from odoo.tests import TransactionCase, new_test_user, tagged

YEAR, MONTH = '2039', '3'            # period 26 Feb 2039 - 25 Mar 2039 (28 days): no live data there
PERIOD_FROM, PERIOD_TO = date(2039, 2, 26), date(2039, 3, 25)


def ae_iban(account16='1234567890123456', bank='033'):
    """A checksum-valid UAE IBAN."""
    bban = bank + account16
    numeric = ''.join(str(int(c, 36)) for c in bban + 'AE00')
    check = 98 - int(numeric) % 97
    return 'AE%02d%s' % (check, bban)


@tagged('post_install', '-at_install', 'country_payroll')
class CountryPayrollCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.Batch = env['payroll.country.batch']
        cls.cfg_ae = env.ref('om_hr_payroll_extended_gk.payroll_country_ae')
        cls.cfg_in = env.ref('om_hr_payroll_extended_gk.payroll_country_in')
        cls.structure = env.ref('om_hr_payroll.structure_base')
        Company = env['res.company']

        def quiet_company(code):
            # creating res.company trips a custom project guard on this DB: reuse the
            # company of that country with the fewest running contracts
            companies = Company.search([('partner_id.country_id.code', '=', code)])
            counts = {c: env['hr.contract'].search_count([('company_id', '=', c.id), ('state', '=', 'open')])
                      for c in companies}
            return min(counts, key=counts.get) if counts else Company
        cls.co_ae = quiet_company('AE')
        cls.co_in = quiet_company('IN')
        if not cls.co_ae or not cls.co_in:
            cls.skipTest(cls, "needs one UAE and one India company")
        cls.co_ae2 = Company.search([('partner_id.country_id.code', '=', 'AE'), ('id', '!=', cls.co_ae.id)], limit=1)
        companies = cls.co_ae | cls.co_in | cls.co_ae2 | env.ref('base.main_company')

        def user(login, groups, **vals):
            u = new_test_user(env, login=login, groups=groups, company_id=cls.co_ae.id,
                              company_ids=[(6, 0, companies.ids)], email='%s@example.com' % login, **vals)
            return u
        # Payroll dropdown: Officer (country = own Leave Location) -> Manager (all) -> Admin (approver)
        officer_groups = 'base.group_user,om_hr_payroll.group_hr_payroll_user'
        cls.officer_in = user('pc_officer_in', officer_groups)
        cls.officer_in.country = 'india'
        cls.officer_ae = user('pc_officer_ae', officer_groups)
        cls.officer_ae.country = 'dubai'
        cls.payroll_admin = user('pc_manager', 'base.group_user,om_hr_payroll.group_hr_payroll_manager')
        cls.payroll_admin.country = 'dubai'
        cls.officer_both = cls.payroll_admin            # a Manager processes every country
        admin_groups = 'base.group_user,om_hr_payroll_extended_gk.group_payroll_admin'
        cls.approver = user('pc_approver', admin_groups)
        cls.approver_in = user('pc_approver_2', admin_groups)
        cls.stranger = user('pc_stranger', 'base.group_user')
        # live contracts of the reused companies would be fetched too: park them (rolled back)
        env['hr.contract'].search([('company_id', 'in', (cls.co_ae | cls.co_in).ids)]).write({'state': 'cancel'})

        cls.emp_ae = cls._employee('PC Dubai One', 'dubai', cls.co_ae, wage=10000, basic_salary=6000, hra=3000,
                                   other_allowance=1000)
        cls.emp_ae2 = cls._employee('PC Dubai Two', 'dubai', cls.co_ae, wage=8000, basic_salary=5000, hra=2000,
                                    other_allowance=1000)
        cls.emp_in = cls._employee('PC India High', 'india', cls.co_in, wage=40000, basic_salary=20000)
        cls.emp_in_low = cls._employee('PC India Low', 'india', cls.co_in, wage=20000)
        cls.worked_overrides = {}

    @classmethod
    def _employee(cls, name, location, company, contract_start=date(2030, 1, 1), contract_end=False,
                  contract_state='open', bank=True, email=True, **contract_vals):
        env = cls.env
        login = name.lower().replace(' ', '_')
        u = new_test_user(env, login=login, groups='base.group_user', company_id=company.id,
                          company_ids=[(6, 0, (company | cls.co_ae).ids)])
        u.country = location
        emp = env['hr.employee'].create({
            'name': name,
            'user_id': u.id,
            'company_id': env.ref('base.main_company').id,
            'work_email': ('%s@example.com' % login) if email else False,
        })
        if bank:
            if location == 'india':
                emp.write({'payroll_bank_name': 'HDFC Bank', 'payroll_bank_holder': name,
                           'bank_account_no': '50100123456789', 'payroll_bank_ifsc': 'HDFC0001234'})
            else:
                emp.write({'payroll_bank_name': 'Emirates NBD', 'payroll_bank_holder': name,
                           'bank_iban_number': ae_iban()})
        vals = dict(name='Contract %s' % name, employee_id=emp.id, company_id=company.id,
                    struct_id=cls.structure.id, date_start=contract_start, date_end=contract_end,
                    state=contract_state)
        vals.update(contract_vals)
        env['hr.contract'].create(vals)
        return emp

    # ------------------------------------------------------------ helpers
    def _fake_worked_days(self, payslip_self, contracts, date_from, date_to):
        """Deterministic stand-in for om_hr_payroll get_worked_day_lines: full
        attendance unless self.worked_overrides[employee] says otherwise."""
        date_from = date.fromisoformat(str(date_from))
        date_to = date.fromisoformat(str(date_to))
        days = (date_to - date_from).days + 1
        sundays = len([1 for i in range(days) if (date_from + timedelta(days=i)).weekday() == 6])
        rows = []
        for contract in contracts:
            over = self.worked_overrides.get(contract.employee_id.id, {})
            leave = over.get('leave', 0.0)
            present = over.get('present', days - sundays - leave)
            for code, n in (('PRESENT', present), ('LEAVE', leave), ('SUNDAY', sundays), ('WORK100', days),
                            ('LATE_DEDUCT', over.get('late', 0.0))):
                if n or code in ('PRESENT', 'SUNDAY', 'WORK100'):
                    rows.append({'name': code, 'sequence': 10, 'code': code, 'number_of_days': n,
                                 'number_of_hours': n * 8, 'contract_id': contract.id})
        return rows

    @contextmanager
    def fake_attendance(self):
        test = self
        cls = type(self.env['hr.payslip'])

        def fake(payslip_self, contracts, date_from, date_to):
            return test._fake_worked_days(payslip_self, contracts, date_from, date_to)
        with patch.object(cls, 'get_worked_day_lines', fake):
            yield

    def _batch(self, cfg, user=None, companies=None):
        user = user or (self.officer_ae if cfg == self.cfg_ae else self.officer_in)
        vals = {'payroll_country_id': cfg.id, 'month': MONTH, 'year': YEAR}
        if companies is not None:
            vals['company_ids'] = [(6, 0, companies.ids)]
        else:
            vals['company_ids'] = [(6, 0, (self.co_ae if cfg == self.cfg_ae else self.co_in).ids)]
        # created in the country's company: that company's Quotation Approver approves it
        company = self.co_ae if cfg == self.cfg_ae else self.co_in
        return self.Batch.with_user(user).with_company(company).with_context(payroll_no_autofetch=True).create(vals)

    def _calculated(self, cfg, user=None):
        batch = self._batch(cfg, user)
        with self.fake_attendance():
            batch.action_fetch_employees()
            batch.action_calculate()
        return batch

    def _line(self, batch, employee):
        return batch.sudo().line_ids.filtered(lambda l: l.employee_id == employee)

    def _keep_only(self, batch, employees):
        """Live contracts of the reused company may be fetched too - keep the test employees only."""
        extra = batch.sudo().line_ids.filtered(lambda l: l.employee_id not in employees)
        extra.payslip_id.unlink()
        extra.unlink()

    def _approved(self, cfg, employees):
        batch = self._batch(cfg)
        with self.fake_attendance():
            batch.action_fetch_employees()
            self._keep_only(batch, employees)
            batch.action_calculate()
            res = batch.action_submit()
        self.assertEqual(batch.state, 'submitted', res['params']['message'])
        batch.with_user(self.approver).action_approve()
        self.assertEqual(batch.state, 'approved')
        return batch
