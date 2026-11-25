def migrate(cr, version):
    """India payroll uses the Salary Administration PF / ESI formula; others stay manual."""
    cr.execute("UPDATE payroll_country SET pf_esi_mode = 'formula' WHERE leave_location = 'india'")
