from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    referral_new = env.ref(
        'referral_crm_gk.stage_referral_new', raise_if_not_found=False
    )
    if not referral_new:
        return

    # Collect all valid referral stage IDs so we know which ones are correct
    referral_stage_ids = env['crm.stage'].search(
        [('x_is_referral_stage', '=', True)]
    ).ids

    # Find referral leads that landed on a non-referral stage (e.g. standard CRM "New")
    stuck_leads = env['crm.lead'].search([
        ('x_is_referral', '=', True),
        ('stage_id', 'not in', referral_stage_ids),
    ])
    if stuck_leads:
        stuck_leads.write({'stage_id': referral_new.id})
