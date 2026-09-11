"""AR Responsible on customer invoices becomes a list of people.

`account_move.ar_responsible_id` (one user) is replaced by
`ar_responsible_ids` (many). The old column is copied into the new relation
table here, before Odoo's end-of-upgrade cleanup drops it -- otherwise the 60
invoices that already name an owner would come out of the upgrade blank, fail
the mandatory-AR-Responsible constraint on the next save, and lose the
confirmation the aged-AR close lock reads.

The follow-up log keeps its own stored copy of the field for the AR export to
group on. It is a compute+store many2many, which Odoo does not backfill onto
existing rows, so the log rows are recomputed at the end.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'account_move' AND column_name = 'ar_responsible_id'
    """)
    if not cr.fetchone():
        _logger.info("AR Responsible: nothing to migrate, the old column is gone.")
        return

    cr.execute("""
        INSERT INTO account_move_ar_responsible_rel (move_id, user_id)
        SELECT id, ar_responsible_id
        FROM   account_move
        WHERE  ar_responsible_id IS NOT NULL
        ON CONFLICT DO NOTHING
        RETURNING move_id
    """)
    move_ids = [row[0] for row in cr.fetchall()]
    _logger.info(
        "AR Responsible: carried the single owner onto %s invoice(s).",
        len(move_ids))

    env = api.Environment(cr, SUPERUSER_ID, {})
    env.invalidate_all()

    # Same people as before the upgrade, so no gate actually changes state --
    # but the stored close-lock fields were last written against a field that
    # no longer exists, so they are refreshed against the new one.
    moves = env['account.move'].browse(move_ids).exists()
    if moves:
        moves._compute_ar_close_lock()
        moves.flush_recordset()

    logs = env['account.invoice.followup.log'].search([])
    if logs:
        logs._compute_ar_responsible_ids()
        logs.flush_recordset()
    _logger.info(
        "AR Responsible: refreshed %s follow-up log row(s).", len(logs))
