def migrate(cr, version):
    """The single File field becomes the multi-file Files field. Turn each stored file into a plain
    attachment of its document (named after its file name) before the old field's cleanup can
    delete it, and remember the pairs for post-migration, which links them once the table exists."""
    cr.execute("""
        CREATE TABLE IF NOT EXISTS hr_dms_file_migration AS
        SELECT a.id AS attachment_id, a.res_id AS document_id
          FROM ir_attachment a
         WHERE a.res_model = 'hr.dms.document' AND a.res_field = 'file' AND a.res_id IS NOT NULL
    """)
    cr.execute("""
        UPDATE ir_attachment a
           SET res_field = NULL, name = COALESCE(NULLIF(d.filename, ''), a.name)
          FROM hr_dms_document d
         WHERE a.res_model = 'hr.dms.document' AND a.res_field = 'file' AND d.id = a.res_id
    """)
