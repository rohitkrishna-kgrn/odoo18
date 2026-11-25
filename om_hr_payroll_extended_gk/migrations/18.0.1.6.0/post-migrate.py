def migrate(cr, version):
    """Existing lines: PF / ESI entry = the country default; lines whose EPF / ESI were
    already typed stay Manual (their typed amounts are kept)."""
    cr.execute("""
        UPDATE payroll_country_line l SET pf_esi_entry = c.pf_esi_mode
          FROM payroll_country c WHERE c.id = l.payroll_country_id
    """)
    cr.execute("""
        UPDATE payroll_country_line SET pf_esi_entry = 'manual'
         WHERE manual_keys LIKE '%,epf,%' OR manual_keys LIKE '%,esi,%'
    """)
