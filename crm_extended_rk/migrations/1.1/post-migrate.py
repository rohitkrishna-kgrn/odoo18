# -*- coding: utf-8 -*-
"""Move the old single-submission discovery fields on crm.lead into the new
crm.lead.discovery.form model (one record per form actually sent), then drop
the now-unused columns from crm_lead.
"""
from psycopg2 import sql

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""
        SELECT id, discovery_form_type, discovery_form_state, discovery_token,
               discovery_sent_date, discovery_submitted_date, discovery_data,
               discovery_summary
        FROM crm_lead
        WHERE discovery_token IS NOT NULL
    """)
    rows = cr.dictfetchall()

    if rows:
        env = api.Environment(cr, SUPERUSER_ID, {})
        submission_model = env['crm.lead.discovery.form']
        for row in rows:
            state = row['discovery_form_state']
            if state not in ('sent', 'submitted'):
                continue
            submission = submission_model.create({
                'lead_id': row['id'],
                # 'einvoicing' was the only form type that existed before this
                # migration, so it's the correct fallback for older rows sent
                # before the multi-form-type selector was introduced.
                'form_type': row['discovery_form_type'] or 'einvoicing',
                'token': row['discovery_token'],
                'state': state,
                'sent_date': row['discovery_sent_date'],
                'submitted_date': row['discovery_submitted_date'],
                'data': row['discovery_data'],
                'summary': row['discovery_summary'],
            })
            # The signature was stored as an ir.attachment linked to the old
            # Binary field on crm.lead; re-point it at the new record instead
            # of duplicating the binary data.
            cr.execute("""
                UPDATE ir_attachment
                SET res_model = 'crm.lead.discovery.form',
                    res_field = 'signature',
                    res_id = %s
                WHERE res_model = 'crm.lead'
                  AND res_field = 'discovery_signature'
                  AND res_id = %s
            """, (submission.id, row['id']))

    for column in (
        'discovery_token', 'discovery_form_state', 'discovery_sent_date',
        'discovery_submitted_date', 'discovery_data', 'discovery_summary',
        'discovery_signature',
    ):
        cr.execute(sql.SQL('ALTER TABLE crm_lead DROP COLUMN IF EXISTS {}').format(
            sql.Identifier(column)))
