"""Invoice Type: stop showing a Completion nobody chose.

`invoice_type_classification` no longer falls back to a derived Completion for
an invoice the billing waterfall has placed at the end of its engagement
(`billing_stage == 'completion'`). Advance / Retainer / Credit Note are still
recognised from the document itself; Completion is now only ever the value a
person picked by hand in the Invoice Type dropdown.

The field is a stored compute and Odoo does not re-run one just because its
method changed (see the 18.0.2.4 migration, which did the mirror image of
this), so the ~1,350 documents currently holding a derived 'completion' would
keep it forever. The recompute is forced here.

`completion_check_state` depends on the classification, so it is recomputed
straight after -- blanking the type switches the completion check off for those
invoices until somebody marks one as a Completion, which is the intended
behaviour: the check tests a claim, and until the claim is made there is
nothing to test. It can only relax a posting gate, never tighten one.

Invoices where someone did choose Completion by hand
(`invoice_type_manual == 'completion'`) are untouched: the compute resolves
them to 'completion' unchanged.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # active_test=False: customer invoices archived by the stale-draft sweep
    # would otherwise keep a stale Invoice Type once restored.
    Move = env['account.move'].with_context(active_test=False)
    moves = Move.search([('move_type', 'in', ('out_invoice', 'out_refund'))])

    cr.execute("""
        SELECT count(*) FROM account_move
         WHERE move_type IN ('out_invoice', 'out_refund')
           AND invoice_type_classification = 'completion'
           AND invoice_type_manual IS DISTINCT FROM 'completion'
    """)
    _logger.info("Invoice Type: clearing %s derived Completion value(s).",
                 cr.fetchone()[0])

    for fname in ('invoice_type_classification', 'completion_check_state'):
        env.add_to_compute(Move._fields[fname], moves)
        moves.flush_recordset([fname])

    cr.execute("""
        SELECT COALESCE(invoice_type_classification, 'blank'), count(*)
          FROM account_move
         WHERE move_type IN ('out_invoice', 'out_refund')
         GROUP BY 1
    """)
    _logger.info("Invoice Type after change: %s", dict(cr.fetchall()))
