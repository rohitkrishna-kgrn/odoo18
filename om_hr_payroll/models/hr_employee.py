from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    _description = 'Employee'

    slip_ids = fields.One2many('hr.payslip', 'employee_id', string='Payslips', readonly=True)
    payslip_count = fields.Integer(compute='_compute_payslip_count', string='Payslip Count',
                                   groups="om_om_hr_payroll.group_hr_payroll_user")

    country_for_leave = fields.Selection(related='user_id.country', string='Country For Leave Model')
    # Sensitive HR/payroll data: restrict to HR Managers so these fields are
    # stripped from reads/views for other users, avoiding the "not available
    # for employee public profiles" AccessError (hr.employee has no read
    # access for non-HR users, so Odoo falls back to hr.employee.public,
    # which does not define these fields).
    employee_no = fields.Char(string='Employee No.', groups='hr.group_hr_user')
    doj = fields.Date(string='DOJ', compute='_compute_doj', store=True, readonly=False, groups='hr.group_hr_user')
    pan_no = fields.Char(string='PAN No', groups='hr.group_hr_user')
    uan_pf_no = fields.Char(string='UAN No (PF)', groups='hr.group_hr_user')
    esi_no = fields.Char(string='ESI No', groups='hr.group_hr_user')
    esi_no_editable = fields.Boolean(string='Allow ESI No Edit', default=False, groups='hr.group_hr_user')
    bank_account_no = fields.Char(string='Bank A/c No', groups='hr.group_hr_user')

    def _compute_payslip_count(self):
        for employee in self:
            employee.payslip_count = len(employee.slip_ids)

    @api.depends('first_contract_date')
    def _compute_doj(self):
        for employee in self:
            if not employee.doj:
                employee.doj = employee.first_contract_date

    @api.onchange('bank_account_no')
    def _onchange_bank_account_no(self):
        if self.bank_account_no and not self.bank_iban_number:
            self.bank_iban_number = self.bank_account_no

    @api.onchange('bank_iban_number')
    def _onchange_bank_iban_number(self):
        if self.bank_iban_number and not self.bank_account_no:
            self.bank_account_no = self.bank_iban_number
