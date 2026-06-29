def migrate(cr, version):
    # Only proceed if the wizard relation table exists in the database.
    # It may be absent on fresh installs (table is created when models load).
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = 'it_folder_add_doc_wizard_rel'
        )
    """)
    if not cr.fetchone()[0]:
        return

    # Drop the existing RESTRICT FK (separate execute to avoid multi-statement quirks)
    cr.execute("""
        ALTER TABLE it_folder_add_doc_wizard_rel
        DROP CONSTRAINT IF EXISTS it_folder_add_doc_wizard_rel_document_id_fkey
    """)

    # Re-add with ON DELETE CASCADE so deleting a document cleans up wizard rows
    cr.execute("""
        ALTER TABLE it_folder_add_doc_wizard_rel
        ADD CONSTRAINT it_folder_add_doc_wizard_rel_document_id_fkey
        FOREIGN KEY (document_id)
        REFERENCES it_document(id)
        ON DELETE CASCADE
    """)
