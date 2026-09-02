"""Backfill Invoice Type on documents the billing plan already calls a completion.

`invoice_type_classification` is a stored compute. Adding the
`_derived_completion_type` fallback to it changes what the method returns, but
Odoo only recomputes a stored field on upgrade when the *field definition*
changes -- the dependency list here is unchanged, so every existing row kept
the NULL it was written with.

That left 1,334 customer documents carrying billing_stage = 'completion' and an
empty Invoice Type at the same time, which is exactly the contradiction the
fallback exists to remove, and it is what left the AR dashboard's advance /
completion split view mostly blank.

Batched deliberately: this server has no swap, and recomputing the whole set in
one transaction is enough memory pressure to matter.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

BATCH = 200


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    moves = env['account.move'].with_context(active_test=False).search([
        ('move_type', 'in', ('out_invoice', 'out_refund')),
        ('billing_stage', '=', 'completion'),
        ('invoice_type_classification', '=', False),
    ])
    _logger.info("Invoice Type backfill: %s document(s) to reclassify.", len(moves))

    done = 0
    for start in range(0, len(moves), BATCH):
        batch = moves[start:start + BATCH]
        batch.modified(['billing_stage'])
        batch._compute_invoice_type_classification()
        batch.flush_recordset(['invoice_type_classification'])
        env.invalidate_all()
        done += len(batch)
        _logger.info("Invoice Type backfill: %s/%s.", done, len(moves))

    _logger.info("Invoice Type backfill complete.")
