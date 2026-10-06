"""Dubai Sick Leave is picked by hand as 'Sick Leave - Full Pay' (15 days a
year) or 'Sick Leave - Half Pay' (30 days a year) - see data/leave_types.xml.
Give every Dubai employee the leave month in progress for both new types, so
Available Balance shows the full pool and an approval has a row to deduct from.
Nothing already filed or stored is touched.
"""
from odoo import api, SUPERUSER_ID, fields
from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Balance = env['leave.balance']
    types = env['leave.type'].search([('sick_pay_tier', '!=', False)])
    anchor = leave_month_anchor(fields.Date.today())
    for user in Balance._leave_eligible_users().filtered(lambda u: u.country == 'dubai'):
        for lt in types:
            if not Balance.search_count([('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
                                         ('date', '=', anchor)]):
                Balance.create({'user_id': user.id, 'leave_type_id': lt.id, 'date': anchor,
                                'balance': lt.annual_entitlement})
