def migrate(cr, version):
    """'Returned for Correction' is gone: a returned form is simply back in Draft (its reason stays
    in return_reason and shows on the form)."""
    cr.execute("UPDATE hr_dms_personal_details SET state = 'draft' WHERE state = 'returned'")
