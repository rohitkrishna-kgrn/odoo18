from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Employees used to need no group; keep existing internal users working."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref('hr_dms.group_hr_dms_employee')
    users = env['res.users'].search([('share', '=', False), ('active', '=', True)])
    group.write({'users': [(4, u.id) for u in users]})
    officer = env.ref('hr_dms.group_hr_dms_officer', raise_if_not_found=False)
    if officer:
        officer.unlink()
