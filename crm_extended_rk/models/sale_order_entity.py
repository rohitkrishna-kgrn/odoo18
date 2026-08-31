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

    # ------------------------------------------------------------------
    # Annual invoice counts — read back from the eInvoicing discovery form
    #
    # The discovery form is the only source of truth for these two numbers:
    # they are never typed, derived or estimated here. They are written solely
    # by sale.order.action_fetch_discovery_invoice_counts(), which matches this
    # row to an "Entity Details" block on the form by entity name.
    # ------------------------------------------------------------------
    # Picked from the client's own discovery form. An exact link beats matching
    # two typed names, so choosing one here fills the name and both counts
    # outright; a row for an entity the form never mentioned is still named by
    # hand and simply stays unlinked.
    discovery_entity_id = fields.Many2one(
        'crm.lead.discovery.entity', string='Entity Name', ondelete='set null',
        copy=False,
        help="Pick this entity from the eInvoicing discovery form the client "
             "submitted. Choosing one fills the entity name and both annual "
             "invoice counts straight from that form.")

    inbound_invoice_count = fields.Integer(
        string='Annual Inbound Invoice Count', readonly=True, copy=False,
        help="Supplier invoices received per year, as stated for this entity "
             "in the eInvoicing discovery form. Never edited here.")
    outbound_invoice_count = fields.Integer(
        string='Annual Outbound Invoice Count', readonly=True, copy=False,
        help="Customer invoices issued per year, as stated for this entity "
             "in the eInvoicing discovery form. Never edited here.")
    discovery_state = fields.Selection(
        [('none', 'Not Fetched'),
         ('matched', 'Matched'),
         ('incomplete', 'Counts Missing'),
         ('ambiguous', 'Duplicate Name'),
         ('unmatched', 'No Match')],
        string='Discovery Form', default='none', readonly=True, copy=False,
        help="Result of matching this entity's name against the Entity Details "
             "on the eInvoicing discovery form.")
    discovery_needs_review = fields.Boolean(
        string='Needs Review', compute='_compute_discovery_needs_review')

    # Blank, never 0, whenever the form did not supply a number: an entity that
    # could not be matched must not read as "zero invoices a year".
    inbound_count_display = fields.Char(
        string='Annual Inbound Invoice Count', compute='_compute_count_display')
    outbound_count_display = fields.Char(
        string='Annual Outbound Invoice Count', compute='_compute_count_display')

    @api.depends('discovery_state')
    def _compute_discovery_needs_review(self):
        for entity in self:
            entity.discovery_needs_review = entity.discovery_state in (
                'incomplete', 'ambiguous', 'unmatched')

    @api.depends('inbound_invoice_count', 'outbound_invoice_count', 'discovery_state')
    def _compute_count_display(self):
        for entity in self:
            matched = entity.discovery_state == 'matched'
            entity.inbound_count_display = (
                '{:,}'.format(entity.inbound_invoice_count) if matched else '')
            entity.outbound_count_display = (
                '{:,}'.format(entity.outbound_invoice_count) if matched else '')

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

    def _vals_from_discovery(self, entity_id):
        """Name and counts copied straight off the picked discovery entity.

        Applied in create/write rather than in an onchange: the count fields are
        readonly, so values the client sent back for them would be dropped and
        the row would save with the counts still empty.
        """
        source = self.env['crm.lead.discovery.entity'].browse(entity_id).exists()
        if not source:
            # Cleared, or pointing at a row that is gone: the link no longer
            # backs the counts, so they go too.
            return {'inbound_invoice_count': 0, 'outbound_invoice_count': 0,
                    'discovery_state': 'none'}
        if not source.has_counts:
            return {'name': source.name, 'inbound_invoice_count': 0,
                    'outbound_invoice_count': 0, 'discovery_state': 'incomplete'}
        return {'name': source.name,
                'inbound_invoice_count': source.inbound_count,
                'outbound_invoice_count': source.outbound_count,
                'discovery_state': 'matched'}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('discovery_entity_id'):
                vals.update(self._vals_from_discovery(vals['discovery_entity_id']))
        return super().create(vals_list)

    def write(self, vals):
        """Renaming a row breaks the match it was populated under, so the
        counts are dropped rather than left behind under a different entity's
        name. Re-run "Fetch Invoice Counts" to repopulate them."""
        if 'discovery_entity_id' in vals:
            # Picking (or clearing) the discovery entity is the stronger signal:
            # it decides the name and the counts together.
            vals = {**vals, **self._vals_from_discovery(vals['discovery_entity_id'])}
        elif 'name' in vals:
            stale = self.filtered(
                lambda entity: entity.discovery_state != 'none'
                and (entity.name or '') != (vals.get('name') or ''))
            if stale:
                super(SaleOrderEntity, stale).write({
                    'discovery_entity_id': False,
                    'inbound_invoice_count': 0,
                    'outbound_invoice_count': 0,
                    'discovery_state': 'none',
                })
        return super().write(vals)
