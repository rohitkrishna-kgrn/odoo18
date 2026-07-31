"""Ticket numbers drop the year segment: CHT/2026/0085 -> CHT/0085 going
forward (existing tickets keep their historical number as-is — retroactively
renumbering them would break any /helpdesk/track/<ticket_number> link
already emailed to a client).

data/helpdesk_sequence.xml is noupdate="1", so the prefix/use_date_range
change on the existing ir.sequence record won't apply via a plain reload
-- pushed through explicitly here, same pattern as this module's other
noupdate-protected fixes. number_next is set to continue past the
highest existing ticket number so the new short format can't collide
with an existing one.
"""
import re
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sequence = env.ref('client_helpdesk_portal.seq_client_helpdesk_ticket', raise_if_not_found=False)
    if not sequence:
        return

    max_seen = 0
    env.cr.execute("SELECT ticket_number FROM client_helpdesk_ticket WHERE ticket_number IS NOT NULL")
    for (ticket_number,) in env.cr.fetchall():
        match = re.search(r'(\d+)$', ticket_number or '')
        if match:
            max_seen = max(max_seen, int(match.group(1)))

    sequence.write({
        'prefix': 'CHT/',
        'use_date_range': False,
        'number_next': max_seen + 1,
    })
