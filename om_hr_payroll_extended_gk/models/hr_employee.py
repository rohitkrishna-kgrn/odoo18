from odoo import api, fields, models

# employee fields a Country Payroll line shows (employee, bank and leave location)
EMPLOYEE_WATCH = {
    'name', 'employee_no', 'barcode', 'department_id', 'job_title', 'job_id', 'doj', 'work_location_id',
    'work_email', 'active', 'departure_date', 'user_id', 'bank_account_id', 'bank_account_no',
    'bank_iban_number', 'bank_route_number', 'payroll_bank_id', 'payroll_bank_name', 'payroll_bank_holder',
    'payroll_bank_branch', 'payroll_bank_ifsc',
}
# ... of which these change the pay (payable window, attendance / leave owner)
EMPLOYEE_PAY = {'departure_date', 'user_id'}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    # Only what the existing employee bank fields (Bank A/c No, IBAN, Route
    # Number, core Bank Account) cannot hold. HR Officers only.
    payroll_bank_id = fields.Many2one(
        'res.bank', string='Bank', groups='hr.group_hr_user', tracking=True,
        domain="[('country', 'in', payroll_bank_country_ids)]",
        help="Banks of the employee's payroll country (Leave Location: India / Dubai).")
    payroll_bank_country_ids = fields.Many2many('res.country', compute='_compute_payroll_bank_country_ids',
                                                groups='hr.group_hr_user')
    payroll_bank_country_id = fields.Many2one('res.country', compute='_compute_payroll_bank_country_ids',
                                              groups='hr.group_hr_user',
                                              help="Country given to a bank created from the Bank dropdown.")
    payroll_bank_holder = fields.Char(string='Account Holder Name', groups='hr.group_hr_user', tracking=True)
    payroll_bank_name = fields.Char(string='Bank Name', groups='hr.group_hr_user', tracking=True,
                                    compute='_compute_payroll_bank_name', store=True, readonly=False)
    payroll_bank_branch = fields.Char(string='Bank Branch', groups='hr.group_hr_user', tracking=True)
    payroll_bank_ifsc = fields.Char(string='IFSC Code', groups='hr.group_hr_user', tracking=True,
                                    help="India: 11 characters, e.g. HDFC0001234.")

    @api.depends('user_id.country')
    def _compute_payroll_bank_country_ids(self):
        configs = self.env['payroll.country'].sudo().search([])
        for emp in self:
            match = configs.filtered(lambda c: c.leave_location and c.leave_location == emp.country_for_leave)
            emp.payroll_bank_country_ids = (match or configs).country_id
            emp.payroll_bank_country_id = match[:1].country_id

    @api.depends('payroll_bank_id')
    def _compute_payroll_bank_name(self):
        for emp in self:
            if emp.payroll_bank_id:
                emp.payroll_bank_name = emp.payroll_bank_id.name

    def write(self, vals):
        res = super().write(vals)
        if 'active' in vals and not vals['active']:
            # an archived employee is never in a payroll: out of every open batch at once
            self.env['payroll.country.batch']._drop_archived_employees(self)
        keys = set(vals) & EMPLOYEE_WATCH
        if keys:
            # open payroll lines show the same values as the employee
            self.env['payroll.country.line']._sync_from_source(
                [('employee_id', 'in', self.ids)], recalc=bool(keys & EMPLOYEE_PAY))
        return res
