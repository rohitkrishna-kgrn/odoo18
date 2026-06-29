def migrate(cr, version):
    # Find all view IDs belonging to it_dms
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'it_dms' AND model = 'ir.ui.view'
    """)
    view_ids = [r[0] for r in cr.fetchall()]
    if not view_ids:
        return

    # Determine actual column type of arch_db
    cr.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_name = 'ir_ui_view' AND column_name = 'arch_db'
    """)
    row = cr.fetchone()
    col_type = row[0] if row else None

    # Strip every ' &amp; ' occurrence so Odoo's translate adapter
    # never encounters a bare & when re-parsing old terms as XML.
    if col_type == 'jsonb':
        cr.execute(
            "UPDATE ir_ui_view "
            "SET arch_db = replace(arch_db::text, ' &amp; ', ' ')::jsonb "
            "WHERE id = ANY(%s) AND arch_db IS NOT NULL",
            (view_ids,)
        )
    elif col_type in ('text', 'character varying'):
        cr.execute(
            "UPDATE ir_ui_view "
            "SET arch_db = replace(arch_db, ' &amp; ', ' ') "
            "WHERE id = ANY(%s) AND arch_db IS NOT NULL",
            (view_ids,)
        )
