def migrate(cr, version):
    """Expiry moved from the document to each file: give every file of a dated document that date,
    so the document's computed earliest expiry comes out unchanged."""
    cr.execute("""
        UPDATE ir_attachment a
           SET hr_dms_expiry_date = d.expiry_date
          FROM hr_dms_document_attachment_rel r
          JOIN hr_dms_document d ON d.id = r.document_id
         WHERE a.id = r.attachment_id AND d.expiry_date IS NOT NULL AND a.hr_dms_expiry_date IS NULL
    """)
