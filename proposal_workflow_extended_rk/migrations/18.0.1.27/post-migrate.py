# -*- coding: utf-8 -*-
"""Switch quotations from the S1-S8 catalogue to the four PDF API services.

The new products (data/product_data.xml) get the old S1's sale taxes - one 5%
VAT per company - and the S1-S8 products are archived, so they drop out of the
product picker while the orders that already hold them keep their lines.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

LEGACY_CODES = ('S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7A', 'S7B', 'S8')


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    templates = env['product.template'].with_context(active_test=False)
    services = templates.search([('einv_pdf_service', '!=', False)])
    legacy = templates.search([
        ('default_code', 'in', LEGACY_CODES),
        ('einv_pdf_service', '=', False),
        ('active', '=', True),
    ])
    source = legacy.filtered(lambda product: product.default_code == 'S1')[:1]
    if source:
        services.write({'taxes_id': [(6, 0, source.taxes_id.ids)]})
    legacy.write({'active': False})
    _logger.info(
        "proposal_workflow_extended_rk: %s PDF API services given %s taxes; archived %s",
        len(services), len(source.taxes_id), ', '.join(legacy.mapped('default_code')))
