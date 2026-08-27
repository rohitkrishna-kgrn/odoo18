"""Turn the completion gate on without stopping work already in progress.

The billing plan itself needs no backfill: `_billing_plan_lines()` derives a
plan from `sale_order.advance_amount` whenever no milestones were entered, so
all 3,301 confirmed engagements are covered the moment the module loads.

Two things do need doing here.

**Re-classify.** `invoice_type_classification` is a stored compute that already
held a value on every one of the 3,975 customer documents, and Odoo does not
recompute a stored field just because its `@api.depends` grew a new entry. Left
alone, the new `billing_stage` would be right and the classification driving the
dashboard would still say every invoice is a Completion. The classification is
forced through the compute engine here.

**Grandfather the drafts.** 919 customer invoices are sitting in draft. Every
one predates the plan, most will not tie to it, and blocking them all at once
would stall the AR desk on invoices nobody raised under the new rule. They are
confirmed with an explicit reason, so the gate applies to invoices raised from
today onwards. The confirmation lapses by itself if someone edits the lines --
`AccountMove.write` clears it -- so an old draft that is reworked comes back
under the check.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

GO_LIVE_REASON = (
    "Draft raised before the completion billing check went live; basis "
    "accepted as-is at go-live."
)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    # active_test=False: 917 customer invoices are archived by the stale-draft
    # sweep, and leaving them out would freeze a stale Invoice Type on every one
    # of them for whenever they are restored.
    Move = env['account.move'].with_context(active_test=False)
    moves = Move.search([('move_type', 'in', ('out_invoice', 'out_refund'))])

    # Order matters, and all three have to be forced. The stage places the
    # invoice on the engagement's plan, the classification reads the stage, and
    # the completion check reads the classification. `completion_check_state`
    # is a brand-new column so Odoo computes it during field init -- but that
    # happens *before* this migration corrects the classification, so it would
    # otherwise be left holding a verdict worked out against the old value,
    # which said every document in the ledger was a Completion.
    for fname in ('billing_stage', 'invoice_type_classification',
                  'completion_check_state'):
        env.add_to_compute(Move._fields[fname], moves)
        moves.flush_recordset([fname])

    cr.execute("""
        SELECT invoice_type_classification, count(*)
          FROM account_move
         WHERE move_type IN ('out_invoice', 'out_refund')
         GROUP BY 1
    """)
    _logger.info("Invoice Type after reclassification: %s", dict(cr.fetchall()))

    cr.execute("""
        UPDATE account_move
           SET completion_confirmed = TRUE,
               completion_confirm_reason = %s,
               completion_confirmed_date = NOW() AT TIME ZONE 'UTC'
         WHERE move_type = 'out_invoice'
           AND state = 'draft'
           AND COALESCE(completion_confirmed, FALSE) = FALSE
    """, (GO_LIVE_REASON,))
    _logger.info(
        "Completion basis: grandfathered %s draft customer invoices raised "
        "before the check went live.", cr.rowcount)
