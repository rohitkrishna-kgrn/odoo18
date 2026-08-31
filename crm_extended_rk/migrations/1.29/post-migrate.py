# -*- coding: utf-8 -*-
"""Backfill the entity rows behind the quotation's Entity Name dropdown.

Forms submitted before `crm.lead.discovery.entity` existed only carry their
answers as JSON. The dropdown reads records, so project every submitted form's
Entity Details once here; from now on `_apply_submission` keeps them in step.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    forms = env['crm.lead.discovery.form'].search([('state', '=', 'submitted')])
    forms._sync_entity_records()
