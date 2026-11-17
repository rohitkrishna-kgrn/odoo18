from odoo import fields, models


class AmlRequest(models.Model):
    _inherit = 'aml.request'

    # Set when the request was cancelled by cancelling its quotation (the
    # cascade in aml_automation_extended_rk's sale.order.write), as opposed
    # to the AML team cancelling it. Only the latter ticks AML/KYC Completed.
    cancelled_with_order = fields.Boolean(copy=False, readonly=True)

    def write(self, vals):
        if vals.get('state') == 'cancelled' and self.env.context.get('aml_first_skip_notify'):
            vals = dict(vals, cancelled_with_order=True)
        return super().write(vals)
