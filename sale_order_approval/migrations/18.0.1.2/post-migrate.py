# -*- coding: utf-8 -*-
"""Backfill 'Create / Edit Products' for existing administrators.

post_init_hook only fires on install, so installations that upgraded into the
per-user checkbox never ran it and left their administrators locked out of
product creation.
"""
from odoo import SUPERUSER_ID, api

from odoo.addons.sale_order_approval.hooks import grant_product_management


def migrate(cr, version):
    if not version:
        return
    grant_product_management(api.Environment(cr, SUPERUSER_ID, {}))
