"""Schedule the stage-reminder cron to run at 09:00 GST (UTC+4 -> 05:00
UTC) daily, instead of whatever arbitrary time it happened to activate
at. ir.cron.nextcall is a plain absolute datetime, not a "time of day"
pattern, so this has to be computed and set explicitly — same logic as
__init__.py's post_init_hook (for fresh installs), duplicated here on
purpose since migration scripts should stay self-contained rather than
import from the module's evolving runtime code.

interval_type='days' then just re-adds 1 day to nextcall after every
firing, which keeps the same UTC hour indefinitely (no DST in UTC).
"""
from datetime import datetime, time, timedelta

from odoo import api, fields, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('client_helpdesk_portal.cron_helpdesk_stage_reminders', raise_if_not_found=False)
    if not cron:
        return
    now = fields.Datetime.now()
    next_run = datetime.combine(now.date(), time(5, 0, 0))
    if next_run <= now:
        next_run += timedelta(days=1)
    cron.write({'nextcall': next_run})
