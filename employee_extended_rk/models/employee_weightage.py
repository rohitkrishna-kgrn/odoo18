from odoo import models, fields

class EmployeeWeightage(models.Model):
    _name = 'employee.weightage'
    _description = 'Employee Weightage'

    name = fields.Char(string='Name', required=True)
    number = fields.Float(string='Number', required=True)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    weightage_id = fields.Many2one('employee.weightage', string='Weightage')
    labour_number = fields.Char(string='Labour Number')
    bank_route_number = fields.Char(string='Route Number')
    bank_iban_number = fields.Char(string='IBAN Number')

    direct_bank = fields.Boolean(string='Direct Bank', default=False)

class HrEmployeePublic(models.Model):
    _inherit = 'hr.employee.public'

    weightage_id = fields.Many2one(
        'employee.weightage',
        string='Weightage',
        related='employee_id.weightage_id',
        readonly=True,
    )
    labour_number = fields.Char(
        string='Labour Number',
        related='employee_id.labour_number',
        readonly=True,
    )
    bank_route_number = fields.Char(
        string='Route Number',
        related='employee_id.bank_route_number',
        readonly=True,
    )
    bank_iban_number = fields.Char(
        string='IBAN Number',
        related='employee_id.bank_iban_number',
        readonly=True,
    )
    direct_bank = fields.Boolean(
        string='Direct Bank',
        related='employee_id.direct_bank',
        readonly=True,
    )