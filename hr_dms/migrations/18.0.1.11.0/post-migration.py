def migrate(cr, version):
    cr.execute("""
        INSERT INTO hr_dms_document_attachment_rel (document_id, attachment_id)
        SELECT document_id, attachment_id FROM hr_dms_file_migration
        ON CONFLICT DO NOTHING
    """)
    cr.execute("DROP TABLE hr_dms_file_migration")
