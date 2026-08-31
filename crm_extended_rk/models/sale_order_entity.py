# -*- coding: utf-8 -*-
"""One row per covered entity on a quotation.

`sale.order.entity_count` is the driver: typing a number generates exactly that
many rows below it (Entity 1, Entity 2, ...), each carrying its own name and
fee. The rows are read back by the proposal PDF (see
`proposal_workflow_extended_rk/models/report_proposal.py`).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SaleOrderEntity(models.Model):
    _name = 'sale.order.entity'
    _description = 'Quotation Covered Entity'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'sale.order', string='Quotation', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)

    # Position in the list — "Entity 1", "Entity 2", ... Not stored: it has to
    # follow a drag-reorder or a deletion straight away, in the form and in the
    # PDF alike.
    entity_no = fields.Integer(
        string='Entity', compute='_compute_entity_no')

    # Deliberately not required: rows are generated the moment a count is typed,
    # and a required name would block saving the quotation until every one of
    # them is filled in.
    name = fields.Char(
        string='Entity Name',
        help="Legal name of the entity covered by this engagement.")

    currency_id = fields.Many2one(
        related='order_id.currency_id', string='Currency', readonly=True)
    price = fields.Monetary(
        string='Price', currency_field='currency_id',
        help="Fee allocated to this entity. The Entity Total is the sum of "
             "these, and both are printed in the proposal PDF.")

    @api.depends('sequence', 'order_id.entity_ids', 'order_id.entity_ids.sequence')
    def _compute_entity_no(self):
        for entity in self:
            siblings = entity.order_id.entity_ids
            # `_origin.id` is 0 for a row that has never been saved, so freshly
            # added rows tie and keep the order the o2m already has them in.
            ordered = list(siblings.sorted(
                key=lambda sibling: (sibling.sequence or 0, sibling._origin.id or 0)))
            entity.entity_no = ordered.index(entity) + 1 if entity in ordered else 0

    @api.constrains('price')
    def _check_price_positive(self):
        for entity in self:
            if entity.price < 0:
                raise ValidationError(_("An entity price cannot be negative."))
