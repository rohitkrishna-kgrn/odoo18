"""Apply the new India/Dubai accrual configuration to the 4 pre-existing
leave.type records (Casual Leave, Sick Leave, Loss of Pay, Compensation
Leave).

These xmlids were created back in 2025-09-03 with ir_model_data.noupdate=True
(same trap documented for the leave-balance crons: see the "noupdate='0' in a
data file does NOT guarantee the record updates" note in this codebase's
history), so data/leave_types.xml's new <field> values for them are silently
skipped by the normal data-file load. A migration script is not gated by
noupdate at all - it is just Python that runs once on this upgrade - so it is
the correct place to actually land these values, instead of hand-editing
ir_model_data on production.

Only the two brand-new leave types (Annual Leave / Sick Leave Full & Half Pay
for Dubai) don't need this: they are new xmlids, so the normal data-file load
creates them with the right values the first time regardless.

Also fixes leave_type_wfh: the data file has archived Work from Home
(active=False) since before this migration existed, with a comment claiming
noupdate="0" "forces this even on existing records" - but its
ir_model_data.noupdate was already stuck True on live, so that never actually
applied. Being blank-scoped (applies to both countries) and still active, it
was selectable by every employee and getting a balance row generated for
every employee every month by the monthly accrual for no reason.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    LeaveType = env['leave.type']

    wfh = env.ref('leave_management_rk.leave_type_wfh', raise_if_not_found=False)
    if wfh and wfh.active:
        wfh.write({'active': False})

    configs = {
        'leave_management_rk.leave_type_lop': {
            'accrual_mode': 'reset',
            'monthly_reset_value': 99999,
            'initial_balance': 99999,
        },
        'leave_management_rk.leave_type_compensation': {
            'accrual_mode': 'carry',
        },
        'leave_management_rk.leave_type_casual': {
            'country_scope': 'india',
            'accrual_mode': 'accrue',
            'monthly_accrual_days': 1,
            'cap_at_entitlement': False,
            'allows_half_day': True,
        },
        'leave_management_rk.leave_type_sick': {
            'country_scope': 'india',
            'accrual_mode': 'reset',
            'monthly_reset_value': 1,
            'allows_half_day': True,
        },
    }

    for xmlid, vals in configs.items():
        record = env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.write(vals)
