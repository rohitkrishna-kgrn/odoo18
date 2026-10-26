def migrate(cr, version):
    """Every category now goes through HR approval. Documents that were approved automatically
    (no approver recorded) go back to the queue; ones an HR user approved stay approved."""
    cr.execute("""
        UPDATE hr_dms_document SET state = 'submitted', approved_date = NULL
         WHERE state = 'approved' AND approved_by IS NULL
    """)
