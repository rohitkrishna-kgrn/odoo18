"""Add the India Casual Leave year-end forfeiture rule (client clarification,
2026-09-24): Casual Leave carries forward month to month through the year as
usual, but whatever is left over in December is forfeited rather than
carried into January - the new leave year starts accruing again from 0.

leave_type_casual is one of the xmlids with ir_model_data.noupdate stuck True
(see 18.0.1.1's migration), so data/leave_types.xml's new
reset_at_year_end=True is silently skipped by the normal data-file load, same
as before.

While here, permanently clear noupdate on the leave types this has bitten
twice now, so a plain data-file edit is enough next time and this class of
migration script stops being necessary for this model.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    casual = env.ref('leave_management_rk.leave_type_casual', raise_if_not_found=False)
    if casual:
        casual.write({'reset_at_year_end': True})

    stuck_xmlids = [
        'leave_type_casual',
        'leave_type_sick',
        'leave_type_lop',
        'leave_type_compensation',
        'leave_type_wfh',
    ]
    imd = env['ir.model.data'].search([
        ('module', '=', 'leave_management_rk'),
        ('model', '=', 'leave.type'),
        ('name', 'in', stuck_xmlids),
        ('noupdate', '=', True),
    ])
    imd.write({'noupdate': False})
