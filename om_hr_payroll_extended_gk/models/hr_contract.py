from odoo import models

from .payroll_line import CONTRACT_COMPONENTS

# contract fields a Country Payroll line shows; all but the reference change the pay
CONTRACT_WATCH = set(CONTRACT_COMPONENTS.values()) | {
    'name', 'date_start', 'date_end', 'state', 'esi_amount', 'epf_amount', 'struct_id', 'resource_calendar_id',
}


class HrContract(models.Model):
    _inherit = 'hr.contract'

    def write(self, vals):
        res = super().write(vals)
        keys = set(vals) & CONTRACT_WATCH
        if keys:
            # open payroll lines show (and pay) the same values as the contract
            self.env['payroll.country.line']._sync_from_source(
                [('contract_id', 'in', self.ids)], recalc=bool(keys - {'name'}))
        return res


class ResPartnerBank(models.Model):
    _inherit = 'res.partner.bank'

    def write(self, vals):
        res = super().write(vals)
        if set(vals) & {'acc_number', 'acc_holder_name', 'bank_id'}:
            # the employee's core Bank Account feeds the payroll bank details
            employees = self.env['hr.employee'].sudo().with_context(active_test=False).search(
                [('bank_account_id', 'in', self.ids)])
            if employees:
                self.env['payroll.country.line']._sync_from_source(
                    [('employee_id', 'in', employees.ids)], recalc=False)
        return res
