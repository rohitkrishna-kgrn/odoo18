# -*- coding: utf-8 -*-
"""Seed the new mailbox Keywords from each mailbox's Mail Lead Tag.

Runs once. Only fills mailboxes whose Keywords are still empty, so it never
overwrites a list someone has already typed. Existing Mail Leads are left
untouched (they default to 'Keyword Match' = True) - only mail imported from
now on is checked.
"""
from odoo import SUPERUSER_ID, api

# Tag name (lower-case) -> starting keyword list. Anything not listed starts
# from the tag name itself; edit on the mailbox form any time.
SEED = {
    'einvoicing': 'e-invoice, e-invoicing, electronic invoice, electronic invoicing',
}


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    for server in env['crm.mail.server'].search([('keywords', '=', False)]):
        name = (server.tag_id.name or '').strip()
        if name:
            server.keywords = SEED.get(name.lower(), name)
