def migrate(cr, version):
    # Use a parameterized query so the '%' in 'RR%(y)s' is stored literally
    # as one percent sign.  Without params, psycopg2 does not convert '%%'
    # and the DB ends up storing 'RR%%(y)s', which Odoo formats to 'RR%(y)s'
    # instead of the expected 'RR26'.
    cr.execute(
        """
        UPDATE ir_sequence
           SET prefix         = %s,
               padding        = %s,
               use_date_range = %s
         WHERE code = %s
        """,
        ('RR%(y)s', 2, True, 'recruitment.request'),
    )

    # Clear noupdate so future XML changes apply on upgrade.
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = %s
           AND name   = %s
        """,
        ('recruitment_gk', 'seq_recruitment_request'),
    )
