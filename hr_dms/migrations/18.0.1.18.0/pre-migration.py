def migrate(cr, version):
    """One form per employee became one *open* form per employee (checked in create), so the
    unique constraint goes; Odoo never drops a constraint removed from the code."""
    cr.execute("ALTER TABLE hr_dms_personal_details DROP CONSTRAINT IF EXISTS hr_dms_personal_details_employee_uniq")
    cr.execute("DELETE FROM ir_model_constraint WHERE name = 'hr_dms_personal_details_employee_uniq'")
