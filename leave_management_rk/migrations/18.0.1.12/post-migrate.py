"""Dubai Annual Leave: accrue from each employee's DOJ and reset on its anniversary.

Replaces 18.0.1.9's calendar-year (January) cycle for Dubai users that have a
DOJ (Employees > Settings > DOJ). The current leave month is rewritten to
2.5 x leave months elapsed in the employee's DOJ cycle (capped at 30) minus
approved Annual Leave since the cycle opened; already-projected FUTURE rows are
dropped so the monthly cron regenerates them. Users with no DOJ keep the old
January cycle and are not touched. Past rows are left alone.
"""
from odoo import api, SUPERUSER_ID, fields
from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor, leave_month_bounds


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lt = env.ref('leave_management_rk.leave_type_annual_dubai', raise_if_not_found=False)
    if not lt:
        return
    Balance = env['leave.balance']
    current = leave_month_anchor(fields.Date.today())
    _s, month_end = leave_month_bounds(current)
    for user in Balance._leave_eligible_users().filtered(lambda u: u.country == 'dubai'):
        if not Balance._uses_doj_cycle(user, lt):
            continue
        Balance.search([('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
                        ('date', '>', current)]).unlink()
        window = Balance._doj_cycle_window(user, current)
        if not window:
            continue  # joins in the future: nothing accrues yet
        accrued = min(lt.monthly_accrual_days * Balance._doj_cycle_months_elapsed(user, current),
                      lt.annual_entitlement)
        taken = sum(env['leave.request'].search([
            ('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', window[0]), ('start_date', '<=', month_end),
        ]).mapped('days_requested'))
        Balance._update_balance(user, lt, current, accrued - taken)
