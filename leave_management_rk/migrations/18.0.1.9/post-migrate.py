"""Dubai Annual Leave: calendar-year accrual (client spec, 2026-10-01).

Replaces 18.0.1.8's "restart after each completed Annual Leave" rule. Annual
Leave now accrues 2.5 days per leave month from January (26 Dec - 25 Jan)
for every Dubai employee, 12 x 2.5 = 30 days at December, and starts again
from zero the following January (reset_at_year_end).

Config: restart_accrual_after_leave off, reset_at_year_end on. The type's
ir_model_data.noupdate was already cleared by 18.0.1.8; reset again defensively.

Data: the live rows were built on the old rule (0 for almost everyone, plus
stale projected rows for two employees), so the current leave month is
rewritten to what the new rule gives - 2.5 x months elapsed since January,
capped at 30, minus approved Annual Leave starting in this leave year - and
any already-projected FUTURE rows are dropped so the monthly cron regenerates
them. Past rows are left alone.
"""
from odoo import api, SUPERUSER_ID, fields
from odoo.addons.leave_management_rk.models.leave_period import (
    leave_month_anchor, leave_month_bounds)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lt = env.ref('leave_management_rk.leave_type_annual_dubai', raise_if_not_found=False)
    if not lt:
        return
    lt.write({'restart_accrual_after_leave': False, 'reset_at_year_end': True})
    env['ir.model.data'].search([
        ('module', '=', 'leave_management_rk'), ('model', '=', 'leave.type'),
        ('name', '=', 'leave_type_annual_dubai'), ('noupdate', '=', True),
    ]).write({'noupdate': False})

    Balance = env['leave.balance']
    current = leave_month_anchor(fields.Date.today())
    year_start = leave_month_bounds(current.replace(month=1))[0]
    _s, month_end = leave_month_bounds(current)
    accrued = min(lt.monthly_accrual_days * current.month, lt.annual_entitlement)

    Balance.search([('leave_type_id', '=', lt.id), ('date', '>', current)]).unlink()
    for user in Balance._leave_eligible_users().filtered(lambda u: u.country == 'dubai'):
        taken = sum(env['leave.request'].search([
            ('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', year_start), ('start_date', '<=', month_end),
        ]).mapped('days_requested'))
        Balance._update_balance(user, lt, current, accrued - taken)
