"""Merge Dubai Sick Leave back into the single Sick Leave type (client
clarification, 2026-09-26): only one "Sick Leave" leave type should exist and
be selectable, for both India and Dubai employees. The Full Pay / Half Pay
split is now computed automatically in Payroll from cumulative approved Sick
Leave for the calendar year (see leave_request.get_dubai_sick_pay_split and
om_hr_payroll's "Sick Leave Half Pay Deduction" salary rule), not from two
separate leave types.

leave_type_sick_full_pay_dubai / leave_type_sick_half_pay_dubai were only
created a couple of days ago (18.0.1.3, live 2026-09-24) and — confirmed on
live before writing this migration — have zero leave.balance or
leave.request rows against them, so they can be unlinked outright. Belt and
braces: if either somehow does have rows by the time this runs (e.g. someone
filed a request against them in between), archive it instead of unlinking so
an ON DELETE RESTRICT foreign key doesn't abort the migration.

leave_type_sick itself keeps its existing (India-only until 18.0.1.3) xmlid;
data/leave_types.xml's plain field updates (country_scope cleared,
requires_dha_certificate, dubai_annual_pool, annual_entitlement) apply
normally on this upgrade since its ir_model_data.noupdate was already cleared
in 18.0.1.3 - no migration needed for that part.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    LeaveType = env['leave.type']

    for xmlid in ('leave_type_sick_full_pay_dubai', 'leave_type_sick_half_pay_dubai'):
        record = env.ref('leave_management_rk.%s' % xmlid, raise_if_not_found=False)
        if not record:
            continue
        in_use = (
            env['leave.balance'].search_count([('leave_type_id', '=', record.id)])
            or env['leave.request'].search_count([('leave_type_id', '=', record.id)])
        )
        if in_use:
            record.write({'active': False})
        else:
            record.unlink()
