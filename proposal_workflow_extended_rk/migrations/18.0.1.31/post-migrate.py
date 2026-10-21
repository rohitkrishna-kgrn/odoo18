# -*- coding: utf-8 -*-
"""Fill the Entities tab of existing orders from their discovery forms.

Until now only Fetch Invoice Counts did this, and it skipped every row nobody
had named. Every non-cancelled order whose opportunity carries a submitted
eInvoicing discovery form is filled the way new ones now are, so the Proposal
and Service Engagement PDFs list the client's entities. Runs here rather than
in crm_extended_rk because the service mapping lives in this module.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    forms = env['crm.lead.discovery.form'].search([
        ('form_type', '=', 'einvoicing'), ('state', '=', 'submitted')])
    orders = env['sale.order'].search([
        ('opportunity_id', 'in', forms.lead_id.ids),
        ('state', '!=', 'cancel'),
    ])
    filled = []
    for order in orders:
        before = len(order.entity_ids)
        try:
            with cr.savepoint():
                order._auto_fill_entities_from_discovery()
        except Exception:
            _logger.exception("Could not fill the entities of %s", order.name)
            continue
        filled.append('%s (%s -> %s rows)' % (order.name, before, len(order.entity_ids)))
    _logger.info("Entities filled from the discovery form on %s orders: %s",
                 len(filled), ', '.join(filled))
