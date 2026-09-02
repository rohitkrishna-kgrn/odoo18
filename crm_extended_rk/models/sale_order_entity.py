# -*- coding: utf-8 -*-
"""One row per covered entity on a quotation.

`sale.order.entity_count` is the driver: typing a number generates exactly that
many rows below it (Entity 1, Entity 2, ...), each carrying its own name, fee
and annual invoice counts. The rows are read back by the proposal PDF (see
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

    # The services this entity is covered for. Display only: only the product
    # names are printed, the fee stays the Price beside it, and the order lines
    # remain what actually gets invoiced (see the entity_amount_total note on
    # sale.order). Limited to sellable products, the same set the order-line
    # picker offers.
    service_ids = fields.Many2many(
        'product.product', 'sale_order_entity_product_rel',
        'entity_id', 'product_id', string='Services',
        domain="[('sale_ok', '=', True)]",
        help="Services covered for this entity. Their names are printed in the "
             "Entity-wise Fee Breakdown in the proposal PDF - names only, with "
             "no reference code or price of their own.")

    currency_id = fields.Many2one(
        related='order_id.currency_id', string='Currency', readonly=True)
    price = fields.Monetary(
        string='Price', currency_field='currency_id',
        help="Fee allocated to this entity. The Entity Total is the sum of "
             "these, and both are printed in the proposal PDF.")

    # ------------------------------------------------------------------
    # Annual invoice counts
    #
    # Two sources, in this order of authority. The eInvoicing discovery form
    # the client submitted, via sale.order.action_fetch_discovery_invoice_counts()
    # or by picking the entity below, is what the counts normally come from.
    # Failing that they are typed in by hand — for an entity the form never
    # mentioned, or one it left unanswered. A row carrying typed numbers is
    # flagged 'manual' so neither the fetch button nor a rename wipes them.
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
        string='Annual Inbound Invoice Count', copy=False,
        help="Supplier invoices received per year. Written by the discovery "
             "form, or typed into the Annual Inbound cell.")
    outbound_invoice_count = fields.Integer(
        string='Annual Outbound Invoice Count', copy=False,
        help="Customer invoices issued per year. Written by the discovery "
             "form, or typed into the Annual Outbound cell.")

    # An integer column cannot hold NULL through the ORM, so "no number yet" is
    # carried by these flags instead of by a 0 — an entity nobody has answered
    # for must never read as "zero invoices a year". One flag per column: a row
    # can legitimately have an inbound count and a still-unknown outbound one.
    inbound_count_set = fields.Boolean(
        string='Inbound Count Entered', copy=False)
    outbound_count_set = fields.Boolean(
        string='Outbound Count Entered', copy=False)

    discovery_state = fields.Selection(
        [('none', 'Not Fetched'),
         ('matched', 'Matched'),
         ('manual', 'Entered Manually'),
         ('incomplete', 'Counts Missing'),
         ('ambiguous', 'Duplicate Name'),
         ('unmatched', 'No Match')],
        string='Discovery Form', default='none', readonly=True, copy=False,
        help="Where this entity's annual invoice counts came from: the result "
             "of matching it against the Entity Details on the eInvoicing "
             "discovery form, or 'Entered Manually' for numbers typed here.")
    discovery_needs_review = fields.Boolean(
        string='Needs Review', compute='_compute_discovery_needs_review')

    # The editable surface for the two counts. Text cells rather than integer
    # ones so an entity nobody has a number for stays blank instead of showing
    # a 0: typing writes the integer behind it and marks the row manual.
    inbound_count_display = fields.Char(
        string='Annual Inbound Invoice Count', compute='_compute_count_display',
        inverse='_inverse_count_display',
        help="Supplier invoices received per year. Filled by Fetch Invoice "
             "Counts, or type it in. Leave it blank when the number is not "
             "known — blank is not the same as 0. A number typed here "
             "stays put the next time the counts are fetched; clear the "
             "cell to hand the row back to the discovery form.")
    outbound_count_display = fields.Char(
        string='Annual Outbound Invoice Count', compute='_compute_count_display',
        inverse='_inverse_count_display',
        help="Customer invoices issued per year. Filled by Fetch Invoice "
             "Counts, or type it in. Leave it blank when the number is not "
             "known — blank is not the same as 0. A number typed here "
             "stays put the next time the counts are fetched; clear the "
             "cell to hand the row back to the discovery form.")

    @api.depends('discovery_state')
    def _compute_discovery_needs_review(self):
        for entity in self:
            entity.discovery_needs_review = entity.discovery_state in (
                'incomplete', 'ambiguous', 'unmatched')

    @api.depends('inbound_invoice_count', 'outbound_invoice_count',
                 'inbound_count_set', 'outbound_count_set')
    def _compute_count_display(self):
        for entity in self:
            entity.inbound_count_display = (
                '{:,}'.format(entity.inbound_invoice_count)
                if entity.inbound_count_set else '')
            entity.outbound_count_display = (
                '{:,}'.format(entity.outbound_invoice_count)
                if entity.outbound_count_set else '')

    def _inverse_count_display(self):
        for entity in self:
            # Both cells are read before anything is written: they share one
            # compute, so writing the inbound integer first would recompute —
            # and so drop — an outbound value typed in the same edit.
            typed = {'inbound': entity.inbound_count_display,
                     'outbound': entity.outbound_count_display}
            vals = {}
            for side, raw in typed.items():
                count, filled = entity._parse_count(raw)
                if not filled and entity.discovery_state == 'matched':
                    # A cell arriving blank on a row the form filled is the
                    # client echoing back a value it never rendered (it happens
                    # when the same save also picks the discovery entity), not
                    # the user emptying it. Retype a number to override one.
                    continue
                if (count != entity['%s_invoice_count' % side]
                        or filled != entity['%s_count_set' % side]):
                    vals['%s_invoice_count' % side] = count
                    vals['%s_count_set' % side] = filled
            if not vals:
                continue
            # A typed number is no longer the form's, so the badge says so and
            # the fetch button knows to leave it alone.
            still_filled = any(
                vals.get('%s_count_set' % side, entity['%s_count_set' % side])
                for side in typed)
            vals['discovery_state'] = 'manual' if still_filled else 'none'
            entity.write(vals)

    @api.model
    def _parse_count(self, raw):
        """A typed annual count as `(value, filled)`.

        Blank means "not known" and is deliberately kept apart from a stated 0.
        """
        text = (raw or '').strip()
        for junk in (',', ' ', ' ', '_'):
            text = text.replace(junk, '')
        if not text:
            return 0, False
        try:
            count = int(text)
        except ValueError:
            raise ValidationError(_(
                "\"%s\" is not a valid annual invoice count. Enter a whole "
                "number, or leave the cell blank if the number is not known "
                "yet.") % raw)
        if count < 0:
            raise ValidationError(_(
                "An annual invoice count cannot be negative."))
        return count, True

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

    def _vals_from_discovery(self, entity_id, keep_manual=False):
        """Name and counts copied straight off the picked discovery entity.

        Applied in create/write rather than in an onchange: the counts live
        behind computed display cells, and an onchange would fight whatever the
        client sent for those.

        `keep_manual` is for a row whose counts were typed by hand. The form has
        no numbers to replace them with in that case, so picking (or clearing)
        an entity only renames the row and leaves the counts alone.
        """
        source = self.env['crm.lead.discovery.entity'].browse(entity_id).exists()
        blank = {'inbound_invoice_count': 0, 'outbound_invoice_count': 0,
                 'inbound_count_set': False, 'outbound_count_set': False}
        if not source:
            # Cleared, or pointing at a row that is gone: the link no longer
            # backs the counts, so they go too.
            return {} if keep_manual else {**blank, 'discovery_state': 'none'}
        if not source.has_counts:
            if keep_manual:
                return {'name': source.name}
            return {'name': source.name, **blank,
                    'discovery_state': 'incomplete'}
        return {'name': source.name,
                'inbound_invoice_count': source.inbound_count,
                'outbound_invoice_count': source.outbound_count,
                'inbound_count_set': True, 'outbound_count_set': True,
                'discovery_state': 'matched'}

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            if vals.get('discovery_entity_id'):
                # What the caller states wins over what the picked entity
                # implies - see write() for why that order matters.
                vals = {**self._vals_from_discovery(vals['discovery_entity_id']),
                        **vals}
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        """Renaming a row breaks the match it was populated under, so counts
        that came from the form are dropped rather than left behind under a
        different entity's name. Counts typed by hand stay: the name was never
        what backed them."""
        if 'discovery_entity_id' in vals:
            # Picking (or clearing) the discovery entity is the stronger signal:
            # it decides the name and the counts together.
            manual = self.filtered(
                lambda entity: entity.discovery_state == 'manual')
            for records, keep_manual in ((manual, True), (self - manual, False)):
                if records:
                    # The picked entity fills in what the caller left unsaid, and
                    # never the other way round: the fetch button clears the link
                    # and states 'unmatched' in one write, and deriving the state
                    # from the now-empty link would quietly downgrade that to
                    # 'Not Fetched'.
                    super(SaleOrderEntity, records).write({
                        **records._vals_from_discovery(
                            vals['discovery_entity_id'], keep_manual=keep_manual),
                        **vals,
                    })
            return True
        if ({'inbound_invoice_count', 'outbound_invoice_count'} & set(vals)
                and 'discovery_state' not in vals):
            # A count written straight to its integer column — an import, a
            # script — is not the form's either, and would otherwise stay
            # invisible behind an unset flag.
            vals = {**vals, 'discovery_state': 'manual'}
            for side in ('inbound', 'outbound'):
                if '%s_invoice_count' % side in vals:
                    vals.setdefault('%s_count_set' % side, True)
        elif 'name' in vals:
            stale = self.filtered(
                lambda entity: entity.discovery_state not in ('none', 'manual')
                and (entity.name or '') != (vals.get('name') or ''))
            if stale:
                super(SaleOrderEntity, stale).write({
                    'discovery_entity_id': False,
                    'inbound_invoice_count': 0,
                    'outbound_invoice_count': 0,
                    'inbound_count_set': False,
                    'outbound_count_set': False,
                    'discovery_state': 'none',
                })
        return super().write(vals)
