from odoo import api, fields, models


class AmlRequest(models.Model):
    _inherit = 'aml.request'

    # Set when the request was cancelled by cancelling its quotation (the
    # cascade in aml_automation_extended_rk's sale.order.write), as opposed
    # to the AML team cancelling it. Only the latter ticks AML/KYC Completed.
    cancelled_with_order = fields.Boolean(copy=False, readonly=True)

    # Every route to a final AML outcome (the AML pipeline's Approve /
    # Bypass / Cancel, the sale order's AML Bypass wizard, which may create
    # a request directly in 'bypassed') ends in create() or write() here.
    # The order's aml_gate_completed is a stored compute, which never goes
    # through sale.order.write(), so the "AML done -> tell the approver"
    # trigger has to live on this side.

    @api.model_create_multi
    def create(self, vals_list):
        order_ids = {vals['sale_order_id'] for vals in vals_list if vals.get('sale_order_id')}
        orders = self.env['sale.order'].sudo().browse(order_ids)
        before = orders._aml_gate_snapshot()
        records = super().create(vals_list)
        orders._aml_notify_if_gate_cleared(before)
        return records

    def write(self, vals):
        if vals.get('state') == 'cancelled' and self.env.context.get('aml_first_skip_notify'):
            vals = dict(vals, cancelled_with_order=True)
        if 'state' not in vals and 'sale_order_id' not in vals:
            return super().write(vals)
        orders = self.sudo().sale_order_id
        before = orders._aml_gate_snapshot()
        result = super().write(vals)
        orders |= self.sudo().sale_order_id
        orders._aml_notify_if_gate_cleared(before)
        return result
