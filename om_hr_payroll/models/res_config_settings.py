from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_om_hr_payroll_account = fields.Boolean(string='Payroll Accounting')
    india_basic_cap = fields.Float(
        string='Basic Salary Threshold (India)', default=25000.0,
        config_parameter='om_hr_payroll.india_basic_cap',
        help="Salary After LOP at or above this amount: Basic Salary = the contract's Basic Salary.")
    india_basic_percent = fields.Float(
        string='Basic Salary % below the Threshold (India)', default=70.0,
        config_parameter='om_hr_payroll.india_basic_percent',
        help="Salary After LOP below the threshold: Basic Salary = this % of Salary After LOP "
             "(that payslip only; the contract is not changed).")
    india_epf_percent = fields.Float(
        string='Employee Provident Fund % (India)', default=12.0,
        config_parameter='om_hr_payroll.india_epf_percent',
        help="Employee Provident Fund = Basic Salary x this %.")
