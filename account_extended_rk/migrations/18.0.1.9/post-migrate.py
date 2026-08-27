"""Retire the pre-existing backlog of unapproved draft customer invoices.

The auto-archive policy starts here, and at the time it was switched on there
were ~917 draft customer invoices already past the 7-day approval window, the
oldest from July 2025, spread over roughly twenty staff. Putting that backlog
through the normal warn-then-archive path would have dumped hundreds of inbox
notifications and To-Do activities on individual users in one morning, so it is
swept in a single quiet pass instead: each invoice gets a chatter note
recording what happened, but no notification and no activity.

Stamping stale_draft_archived_date is what keeps the cron off them afterwards —
anything restored from the archive is never auto-archived a second time.
"""

GRACE_DAYS = 7


def migrate(cr, version):
    # mt_note (rather than mt_comment) keeps these as internal log entries that
    # notify nobody, which is the entire point of the quiet sweep.
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'mail' AND name = 'mt_note' AND model = 'mail.message.subtype'
    """)
    row = cr.fetchone()
    subtype_id = row[0] if row else None

    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'base' AND name = 'partner_root' AND model = 'res.partner'
    """)
    row = cr.fetchone()
    author_id = row[0] if row else None

    cr.execute("""
        SELECT id FROM account_move
         WHERE state = 'draft'
           AND move_type IN ('out_invoice', 'out_refund')
           AND active IS TRUE
           AND stale_draft_archived_date IS NULL
           AND create_date < (now() AT TIME ZONE 'UTC') - INTERVAL '%s days'
    """ % GRACE_DAYS)
    move_ids = [r[0] for r in cr.fetchall()]
    if not move_ids:
        return

    if subtype_id and author_id:
        cr.execute("""
            INSERT INTO mail_message (
                model, res_id, body, message_type, subtype_id, author_id,
                is_internal, date, create_uid, create_date, write_uid, write_date
            )
            SELECT 'account.move', m.id,
                   '<p>Archived automatically when the unapproved-draft policy '
                   'was switched on: this invoice had been sitting in draft for '
                   'more than %s days without being approved. Use '
                   '<b>Action &#8594; Unarchive</b> to bring it back.</p>',
                   'notification', %%s, %%s,
                   TRUE, now() AT TIME ZONE 'UTC', 1, now() AT TIME ZONE 'UTC',
                   1, now() AT TIME ZONE 'UTC'
              FROM account_move m
             WHERE m.id = ANY(%%s)
        """ % GRACE_DAYS, (subtype_id, author_id, move_ids))

    cr.execute("""
        UPDATE account_move
           SET active = FALSE,
               stale_draft_archived_date = (now() AT TIME ZONE 'UTC')::date
         WHERE id = ANY(%s)
    """, (move_ids,))
