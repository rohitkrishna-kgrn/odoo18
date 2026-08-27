"""Invoice Type: stop guessing Completion, leave it blank to be chosen.

Advance, Retainer and Credit Note are facts the document gives away, so they
stay automatic. Completion is a judgement -- "this invoice closes the
engagement" -- so from now on nobody's judgement is invented for them: the
field arrives blank and the person raising the invoice picks it.

`invoice_type_classification` is a stored compute, and Odoo does not re-run one
just because its method changed, so the 2,581 documents currently holding an
auto-assigned 'completion' would keep it forever. The recompute is forced here.
`invoice_type_manual` is a brand-new column and therefore NULL on every row, so
the compute resolves each of them to blank -- except the ones that genuinely
classify themselves, which keep Advance / Retainer / Credit Note.

`completion_check_state` follows the classification, so it is recomputed after
it. Blanking the type switches the check off for those invoices until somebody
marks one as a Completion, which is the intended behaviour: the check exists to
test the claim, and until the claim is made there is nothing to test.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # active_test=False: 917 customer invoices are archived by the stale-draft
    # sweep and would otherwise keep a stale Invoice Type once restored.
    Move = env['account.move'].with_context(active_test=False)
    moves = Move.search([('move_type', 'in', ('out_invoice', 'out_refund'))])

    cr.execute("""
        SELECT count(*) FROM account_move
         WHERE move_type IN ('out_invoice', 'out_refund')
           AND invoice_type_classification = 'completion'
    """)
    _logger.info("Invoice Type: clearing %s auto-assigned Completion values.",
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
