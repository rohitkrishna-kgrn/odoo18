"""Dubai Annual Leave: 2 days/month from DOJ, remaining balance carried forward.

Supersedes 18.0.1.12's anniversary reset and 18.0.1.9's 2.5/month + 30 cap.
The current leave month is rewritten to 2 x leave months since the DOJ minus
all approved Annual Leave since the DOJ; projected FUTURE rows are dropped for
the cron to regenerate. Users without a DOJ and past rows are left alone.
"""
from odoo import api, SUPERUSER_ID, fields
from odoo.addons.leave_management_rk.models.leave_period import leave_month_anchor, leave_month_bounds


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lt = env.ref('leave_management_rk.leave_type_annual_dubai', raise_if_not_found=False)
    if not lt:
        return
    lt.write({'monthly_accrual_days': 2.0, 'cap_at_entitlement': False,
              'reset_at_year_end': False, 'restart_accrual_after_leave': False})
    env['ir.model.data'].search([
        ('module', '=', 'leave_management_rk'), ('model', '=', 'leave.type'),
        ('name', '=', 'leave_type_annual_dubai'), ('noupdate', '=', True),
    ]).write({'noupdate': False})

    Balance = env['leave.balance']
    current = leave_month_anchor(fields.Date.today())
    for user in Balance._leave_eligible_users().filtered(lambda u: u.country == 'dubai'):
        if not Balance._uses_doj_cycle(user, lt):
            continue
        Balance.search([('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
                        ('date', '>', current)]).unlink()
        window = Balance._doj_cycle_window(user, current)
        if not window:
            continue  # joins in the future: nothing accrues yet
        accrued = lt.monthly_accrual_days * Balance._doj_cycle_months_elapsed(user, current)
        taken = sum(env['leave.request'].search([
            ('user_id', '=', user.id), ('leave_type_id', '=', lt.id),
            ('state', '=', 'approved'),
            ('start_date', '>=', window[0]), ('start_date', '<=', window[1]),
        ]).mapped('days_requested'))
        Balance._update_balance(user, lt, current, accrued - taken)
