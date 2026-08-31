# -*- coding: utf-8 -*-
"""The Entity Details blocks of a discovery form, as records.

The submission stores its answers as one JSON blob. These rows are that blob's
per-entity projection, so a quotation can offer the client's own entity names in
a dropdown and link to one exactly, instead of hoping two typed names match.

Rows are rebuilt from the payload by `crm.lead.discovery.form._sync_entity_records()`
and are never edited by hand: the submitted form stays the source of truth.
"""
from odoo import fields, models


def parse_invoice_count(value):
    """A submitted count as an int, or None when the form carried no usable
    number. Never substitutes a default: a missing count has to stay missing.

    Not `value in (None, '', False)` - 0 == False in Python, and a stated count
    of 0 is a real answer that must survive as 0 rather than read as "missing".
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def entity_name_key(name):
    """Names are compared on a normalised key: case and inner spacing routinely
    differ between what the client typed into the form and what was typed onto
    the quotation ("ABC  Pvt Ltd" / "abc pvt ltd"). Nothing else is normalised,
    so two genuinely different names never collide."""
    return ' '.join((name or '').split()).casefold()


class CrmLeadDiscoveryEntity(models.Model):
    _name = 'crm.lead.discovery.entity'
    _description = 'Discovery Form Entity'
    _order = 'form_id, sequence, id'

    form_id = fields.Many2one(
        'crm.lead.discovery.form', string='Discovery Form',
        required=True, ondelete='cascade', index=True)
    lead_id = fields.Many2one(
        related='form_id.lead_id', string='Opportunity', store=True, index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Entity Name', required=True)
    inbound_count = fields.Integer(string='Annual Inbound Invoice Count')
    outbound_count = fields.Integer(string='Annual Outbound Invoice Count')
    # Both counts were actually stated. Kept as its own flag because an ORM
    # integer reads back as 0, so a missing answer is otherwise indistinguishable
    # from a stated zero.
    has_counts = fields.Boolean(string='Counts Stated')
