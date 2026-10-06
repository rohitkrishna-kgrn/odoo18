"""Re-run of the 18.0.1.16 Dubai balance recompute: a manual run of the monthly cron overwrote it.

- Annual Leave: every row read 2 (the 18.0.1.14 backfill failed on live and left
  the generic +2). Rewritten to 2 x leave months since the DOJ anniversary (since
  January with no DOJ) minus approved Annual Leave in that cycle. It then carries
  month to month and is only reset on the DOJ anniversary.
- Sick Leave - Full / Half Pay: rewritten to 15 / 30 minus approved days this leave
  year. Days Dubai staff took earlier this year on the plain 'Sick Leave' type
  (filed before the two pay tiers existed) are counted against the pools too -
  first 15 days against Full Pay, the rest against Half Pay.
"""
from odoo import api, SUPERUSER_ID, fields
from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor, leave_month_bounds


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Balance = env['leave.balance']
    Request = env['leave.request']
    annual = env.ref('leave_management_rk.leave_type_annual_dubai', raise_if_not_found=False)
    full = env.ref('leave_management_rk.leave_type_sick_full_pay_dubai', raise_if_not_found=False)
    half = env.ref('leave_management_rk.leave_type_sick_half_pay_dubai', raise_if_not_found=False)
    legacy = env.ref('leave_management_rk.leave_type_sick', raise_if_not_found=False)
    current = leave_month_anchor(fields.Date.today())
    _s, month_end = leave_month_bounds(current)
    year_start, _e = leave_month_bounds(current.replace(month=1))

    def taken(user, lt, start):
        return sum(Request.search([
            ('user_id', '=', user.id), ('leave_type_id', '=', lt.id), ('state', '=', 'approved'),
            ('start_date', '>=', start), ('start_date', '<=', month_end),
        ]).mapped('days_requested'))

    for user in Balance._leave_eligible_users().filtered(lambda u: u.country == 'dubai'):
        if annual:
            window = Balance._doj_cycle_window(user, current) if Balance._uses_doj_cycle(user, annual) else None
            if Balance._uses_doj_cycle(user, annual) and not window:
                pass  # joins in the future: nothing accrues yet
            else:
                start = window[0] if window else year_start
                months = (Balance._doj_cycle_months_elapsed(user, current) if window else current.month)
                Balance._update_balance(user, annual, current,
                                        annual.monthly_accrual_days * months - taken(user, annual, start))
        if full and half:
            legacy_days = taken(user, legacy, year_start) if legacy else 0.0
            legacy_full = min(legacy_days, full.annual_entitlement)
            legacy_half = min(legacy_days - legacy_full, half.annual_entitlement)
            Balance._update_balance(user, full, current,
                                    full.annual_entitlement - taken(user, full, year_start) - legacy_full)
            Balance._update_balance(user, half, current,
                                    half.annual_entitlement - taken(user, half, year_start) - legacy_half)
