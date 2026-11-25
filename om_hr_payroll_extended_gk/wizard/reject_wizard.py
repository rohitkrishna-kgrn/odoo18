from odoo import fields, models


class PayrollCountryRejectWizard(models.TransientModel):
    """Reason popup for Reject and for Resubmission."""
    _name = 'payroll.country.reject.wizard'
    _description = 'Reject / Resubmit Payroll Batch'

    batch_id = fields.Many2one('payroll.country.batch', required=True, readonly=True)
    mode = fields.Selection([('reject', 'Reject'), ('resubmit', 'Resubmission')], default='reject', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'resubmit':
            self.batch_id._do_resubmit(self.reason)
        else:
            self.batch_id._do_reject(self.reason)
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
