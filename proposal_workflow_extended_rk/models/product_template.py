# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_einvoicing_product = fields.Boolean(
        string='eInvoicing Product',
        help="Reporting flag marking this product as part of the eInvoicing "
             "service catalogue. Filterable and groupable in product list views; "
             "it does not change how the proposal is built.")

    proposal_scope = fields.Text(
        string='Scope of Work',
        help="Shown in the proposal under 'Scope of Services'. One bullet per "
             "line — each line becomes a separate bullet in the PDF. Copied onto "
             "the quotation's Proposal tab when this product is added to an order, "
             "where it can still be edited for that specific proposal.")

    proposal_methodology = fields.Text(
        string='Methodology',
        help="Shown in the proposal under 'Delivery Methodology'. One bullet per "
             "line. Copied onto the quotation's Proposal tab, where it stays editable.")

    proposal_deliverables = fields.Text(
        string='Deliverables',
        help="Shown in the proposal under 'Deliverables'. One deliverable per line. "
             "Optional — the Deliverables section is omitted from the PDF when no "
             "service on the order has any.")
