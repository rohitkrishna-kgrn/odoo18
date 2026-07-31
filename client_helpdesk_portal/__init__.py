from datetime import datetime, time, timedelta

from odoo import fields

from . import models
from . import controllers


def post_init_hook(env):
    """Backfill one Helpdesk Portal User row per active employee (Select
    Access off by default) so managers see the full roster immediately
    instead of an empty configuration list."""
    Employee = env['hr.employee']
    PortalUser = env['client.helpdesk.portal.user']
    existing = PortalUser.with_context(active_test=False).search([]).mapped('employee_id').ids
    missing = Employee.search([('active', '=', True), ('id', 'not in', existing or [0])])
    PortalUser.create([{'employee_id': emp.id} for emp in missing])

    _schedule_reminder_cron_at_9am_gst(env)


def _schedule_reminder_cron_at_9am_gst(env):
    """ir.cron.nextcall is an absolute UTC datetime, not a "time of day"
    pattern, so it can't be expressed declaratively in the cron's XML data
    — set it here to the next occurrence of 05:00 UTC (09:00 GST, UTC+4).
    interval_type='days' then just re-adds 1 day to nextcall after every
    firing, which keeps the same UTC hour indefinitely (no DST in UTC)."""
    cron = env.ref('client_helpdesk_portal.cron_helpdesk_stage_reminders', raise_if_not_found=False)
    if not cron:
        return
    now = fields.Datetime.now()
    next_run = datetime.combine(now.date(), time(5, 0, 0))
    if next_run <= now:
        next_run += timedelta(days=1)
    cron.write({'nextcall': next_run})
