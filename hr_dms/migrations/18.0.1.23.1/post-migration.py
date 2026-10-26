def migrate(cr, version):
    """A form sent back to Draft is no longer verified: drop the stale 'Verified by'."""
    cr.execute("UPDATE hr_dms_personal_details SET verified_by = NULL, verified_date = NULL "
               "WHERE state = 'draft' AND verified_by IS NOT NULL")
