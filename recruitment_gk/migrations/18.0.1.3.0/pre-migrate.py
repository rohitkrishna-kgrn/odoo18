def migrate(cr, version):
    cr.execute("""
        ALTER TABLE recruitment_request
            ADD COLUMN IF NOT EXISTS salary_currency VARCHAR;
        ALTER TABLE recruitment_candidate
            ADD COLUMN IF NOT EXISTS salary_currency VARCHAR;
    """)
