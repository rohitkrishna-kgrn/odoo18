def migrate(cr, version):
    # Drop old Float columns so Odoo recreates them as VARCHAR for the
    # new Selection fields (total_experience, relevant_experience).
    # notice_period was already Char (VARCHAR) — no action needed.
    for col in ('total_experience', 'relevant_experience'):
        cr.execute(
            "ALTER TABLE recruitment_candidate DROP COLUMN IF EXISTS %s" % col
        )
