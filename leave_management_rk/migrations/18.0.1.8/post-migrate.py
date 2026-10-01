"""Dubai Annual Leave accrual rework (client spec, 2026-09-29): instead of
accruing continuously from whenever a Dubai employee became eligible, Annual
Leave now only builds up from zero starting the leave month right after the
employee's own most recently COMPLETED approved Annual Leave request ended -
see leave.type's restart_accrual_after_leave and
LeaveBalance._restart_cycle_anchor.

Two field values need to land on the pre-existing leave_type_annual_dubai
record: the corrected monthly rate (2 -> 2.5, since 2/month only reaches 24
days/year against a 30-day entitlement) and the new
restart_accrual_after_leave=True flag. Confirmed on live before writing this:
leave_type_annual_dubai's ir_model_data.noupdate is already stuck True from
its original creation (same trap documented for leave_type_casual/sick/lop/
compensation/wfh in 18.0.1.2's own migration), so data/leave_types.xml's new
values are silently skipped by the normal data-file load. A migration script
is not gated by noupdate at all, so it is the correct place to land these
values, instead of hand-editing production. While here, also clear this
xmlid's noupdate (as 18.0.1.3 did for the other five), so a plain data-file
edit is enough for this record from now on.

Not a data-loss concern: this only changes two configuration fields on one
leave.type record. No leave.balance or leave.request row is touched. Existing
stored balances for Dubai employees keep whatever the (correct, pre-existing)
monthly cron already accrued for them under the old 2/month rate; going
forward, the corrected 2.5/month rate applies, and any Dubai employee with a
completed Annual Leave in their history has their accrual cycle re-anchored
next time the monthly cron runs.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    annual_dubai = env.ref('leave_management_rk.leave_type_annual_dubai', raise_if_not_found=False)
    if annual_dubai:
        annual_dubai.write({
            'monthly_accrual_days': 2.5,
            'restart_accrual_after_leave': True,
        })

    imd = env['ir.model.data'].search([
        ('module', '=', 'leave_management_rk'),
        ('model', '=', 'leave.type'),
        ('name', '=', 'leave_type_annual_dubai'),
        ('noupdate', '=', True),
    ])
    imd.write({'noupdate': False})
