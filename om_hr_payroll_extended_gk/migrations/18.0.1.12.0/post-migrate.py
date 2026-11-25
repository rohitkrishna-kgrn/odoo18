from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """One approver per batch: the Quotation Approver of the company the batch was
    created in. Existing batches get their creator's company, then their approver."""
    cr.execute("""
        UPDATE payroll_country_batch b SET company_id = u.company_id
          FROM res_users u WHERE u.id = b.create_uid AND u.company_id IS NOT NULL
    """)
    env = api.Environment(cr, SUPERUSER_ID, {})
    batches = env['payroll.country.batch'].with_context(active_test=False).search([])
    batches.invalidate_recordset(['company_id'])
    batches._compute_approver_user_ids()
    batches.flush_recordset()
