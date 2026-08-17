# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrderProposalLine(models.Model):
    _name = 'sale.order.proposal.line'
    _description = 'Quotation Proposal Service Narrative'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'sale.order', string='Quotation', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)

    product_id = fields.Many2one(
        'product.product', string='Service', required=True, ondelete='cascade')
    name = fields.Char(
        string='Service Name', required=True,
        help="Heading used for this service throughout the proposal PDF.")
    code = fields.Char(
        string='Ref',
        help="Short code shown in the orange badge next to the service name "
             "(e.g. S1, S4). Defaults to the product's internal reference.")

    # One bullet per line — the report splits on newlines.
    scope = fields.Text(string='Scope of Work')
    methodology = fields.Text(string='Methodology')
    deliverables = fields.Text(string='Deliverables')

    is_einvoicing_product = fields.Boolean(
        related='product_id.is_einvoicing_product', string='eInvoicing', readonly=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Pull the narrative off the product when a service is picked by hand."""
        for line in self:
            if not line.product_id:
                continue
            template = line.product_id.product_tmpl_id
            line.name = line.product_id.name
            line.code = line.product_id.default_code or False
            line.scope = template.proposal_scope
            line.methodology = template.proposal_methodology
            line.deliverables = template.proposal_deliverables
