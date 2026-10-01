def migrate(cr, version):
    """The short-lived 'Loss of Pay' (LOPC) category is gone: LOP is a deduction again.
    Move any payslip lines/rules recomputed under it back to Deduction."""
    cr.execute("""
        UPDATE hr_payslip_line SET category_id = (SELECT res_id FROM ir_model_data
            WHERE module='om_hr_payroll' AND name='DED')
        WHERE category_id IN (SELECT res_id FROM ir_model_data
            WHERE module='om_hr_payroll' AND name='LOPC')
    """)
