def migrate(cr, version):
    # Strip stale multi-language arch translations for all it_dms views.
    # Previous arch stored "Ownership &amp; Version" as a group string; that
    # decoded term ("Ownership & Version") is saved in arch_db and causes
    # XMLSyntaxError in translate.adapter on every subsequent upgrade.
    # Resetting to en_US-only removes the bad term so the new arch can be saved.
    cr.execute("""
        UPDATE ir_ui_view v
        SET    arch_db = jsonb_build_object('en_US', v.arch_db->>'en_US')
        FROM   ir_model_data d
        WHERE  d.model  = 'ir.ui.view'
          AND  d.module = 'it_dms'
          AND  d.res_id = v.id
          AND  v.arch_db IS NOT NULL
          AND  jsonb_typeof(v.arch_db) = 'object'
    """)
