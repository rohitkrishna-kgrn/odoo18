def migrate(cr, version):
    # Truncate stale TransientModel wizard relation rows before models load.
    # These rows have document_id values that no longer exist (it_document may
    # not exist yet), which would cause the FK creation to fail during upgrade.
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'it_folder_add_doc_wizard_rel'
        )
    """)
    if cr.fetchone()[0]:
        cr.execute("DELETE FROM it_folder_add_doc_wizard_rel")
