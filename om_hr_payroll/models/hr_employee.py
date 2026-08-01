from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    _description = 'Employee'

    slip_ids = fields.One2many('hr.payslip', 'employee_id', string='Payslips', readonly=True)
    payslip_count = fields.Integer(compute='_compute_payslip_count', string='Payslip Count',
                                   groups="om_om_hr_payroll.group_hr_payroll_user")

    country_for_leave = fields.Selection(related='user_id.country', string='Country For Leave Model')
    employee_no = fields.Char(string='Employee No.')
    doj = fields.Date(string='DOJ', compute='_compute_doj', store=True, readonly=False)
    pan_no = fields.Char(string='PAN No')
    uan_pf_no = fields.Char(string='UAN No (PF)')
    esi_no = fields.Char(string='ESI No')
    esi_no_editable = fields.Boolean(string='Allow ESI No Edit', default=False)
    bank_account_no = fields.Char(string='Bank A/c No')

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
