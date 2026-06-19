from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    manager_grp = env.ref('referral_crm_gk.group_referral_manager', raise_if_not_found=False)
    user_grp = env.ref('referral_crm_gk.group_referral_user', raise_if_not_found=False)

    if not manager_grp or not user_grp:
        return

    # Shared menus — visible to both User and Manager
    shared = [
        'referral_crm_gk.menu_referral_root',
        'referral_crm_gk.menu_referral_dashboard',
        'referral_crm_gk.menu_referral_pipeline',
        'referral_crm_gk.menu_referral_my_leads',
        'referral_crm_gk.menu_referral_all',
        'referral_crm_gk.menu_referral_referrers',
        'referral_crm_gk.menu_referral_commissions',
    ]
    for xmlid in shared:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.write({'groups_id': [(6, 0, [user_grp.id, manager_grp.id])]})

    # Configuration menus — Manager only
    config = [
        'referral_crm_gk.menu_referral_config',
        'referral_crm_gk.menu_referral_config_settings',
        'referral_crm_gk.menu_referral_config_stages',
        'referral_crm_gk.menu_referral_config_tags',
    ]
    for xmlid in config:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.write({'groups_id': [(6, 0, [manager_grp.id])]})
