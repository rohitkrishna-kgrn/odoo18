"""Move the Follow-up Log from a notebook tab to the invoice chatter.

Three jobs, all of them one-off:

1. Seed `mail.activity.type.ar_followup_method` on the types that already
   exist. The field has no compute -- a compute that seeds itself from `name`
   would either recurse or silently undo a mapping AR set by hand -- so the
   19 existing types would otherwise all sit blank and every completed
   activity would log as 'Other'.

2. Stamp `source` on the rows entered through the old tab. They have no
   chatter message behind them, which is exactly what 'manual' means, and the
   column would otherwise read as a Log note that cannot be opened.

3. Backfill follow-ups from chatter history already on customer invoices, so
   the AR reports do not show a client as never chased when the chatter plainly
   says otherwise. Only messages that qualify under the new rule are read:
   typed Log notes and activity-done messages. The ~21,000 field-tracking
   messages on account.move share the Note subtype but are message_type
   'notification' with no activity type, and are left alone.

The stored no-follow-up flag and last-follow-up fields are recomputed at the
end for every invoice that gained a row, otherwise the red No Follow-Up Logged
banner would stay up on invoices that now have a documented chase.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

BATCH = 500


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    # -- 1. seed the activity type -> method mapping --------------------
    ActivityType = env['mail.activity.type']
    types = ActivityType.with_context(active_test=False).search(
        [('ar_followup_method', '=', False)])
    for atype in types:
        atype.ar_followup_method = ActivityType._guess_ar_followup_method(
            atype.name, atype.category)
    _logger.info(
        "Follow-up log: seeded AR method on %s activity type(s): %s",
        len(types),
        ", ".join("%s=%s" % (t.name, t.ar_followup_method) for t in types) or "none",
    )

    # -- 2. legacy hand-entered rows are 'manual' -----------------------
    cr.execute("""
        UPDATE account_invoice_followup_log
           SET source = 'manual'
         WHERE message_id IS NULL
           AND (source IS NULL OR source != 'manual')
    """)
    _logger.info("Follow-up log: %s legacy row(s) marked manual.", cr.rowcount)

    # -- 3. backfill from chatter history -------------------------------
    # Narrowed in SQL rather than by browsing every message on every invoice:
    # account.move carries ~30,000 messages and all but a handful are tracking
    # notifications.
    cr.execute("""
        SELECT m.id, m.res_id
          FROM mail_message m
          JOIN account_move am ON am.id = m.res_id
     LEFT JOIN mail_message_subtype s ON s.id = m.subtype_id
     LEFT JOIN account_invoice_followup_log l ON l.message_id = m.id
         WHERE m.model = 'account.move'
           AND am.move_type IN ('out_invoice', 'out_refund')
           AND l.id IS NULL
           AND (
                m.mail_activity_type_id IS NOT NULL
                OR (m.message_type = 'comment' AND s.internal IS TRUE)
           )
      ORDER BY m.id
    """)
    rows = cr.fetchall()
    _logger.info("Follow-up log: %s chatter message(s) to backfill.", len(rows))

    Log = env['account.invoice.followup.log'].sudo()
    created = skipped = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        messages = env['mail.message'].browse([r[0] for r in batch])
        moves = env['account.move'].browse([r[1] for r in batch])
        vals_list = []
        for message, move in zip(messages, moves):
            if not message.exists() or not move.exists():
                skipped += 1
                continue
            # feedback is not recoverable for a historic activity -- the
            # rendered body is all that was ever stored -- so _prepare_from_
            # message falls back to it, which is the best record there is.
            vals = Log._prepare_from_message(move, message)
            if vals:
                vals_list.append(vals)
            else:
                skipped += 1
        if vals_list:
            Log.create(vals_list)
            created += len(vals_list)
        env.invalidate_all()
        _logger.info(
            "Follow-up log backfill: %s/%s message(s) processed.",
            min(start + BATCH, len(rows)), len(rows))

    _logger.info(
        "Follow-up log: %s row(s) created, %s message(s) skipped.",
        created, skipped)

    # -- 4. refresh the stored fields the AR reports read ---------------
    move_ids = sorted({r[1] for r in rows})
    if move_ids:
        moves = env['account.move'].browse(move_ids).exists()
        moves.modified(['followup_log_ids'])
        moves._compute_last_followup()
        moves._compute_followup_log_status()
        moves._compute_ar_no_followup_flag()
        moves._compute_ar_close_lock()
        moves.flush_recordset()
        _logger.info(
            "Follow-up log: refreshed AR fields on %s invoice(s).", len(moves))

    _logger.info("Follow-up log chatter migration complete.")
