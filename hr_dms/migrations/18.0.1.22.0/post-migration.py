def migrate(cr, version):
    """Categories archived before the cascade existed still had active documents showing."""
    cr.execute("""
        UPDATE hr_dms_document d
           SET active = FALSE, archived_by_category = TRUE
          FROM hr_dms_category c
         WHERE c.id = d.category_id AND NOT c.active AND d.active
    """)
