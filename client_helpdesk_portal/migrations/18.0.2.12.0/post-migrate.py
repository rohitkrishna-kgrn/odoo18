"""Revert 18.0.2.11.0's coupling of client.helpdesk.portal.user.active to
the linked Odoo user's active status.

That change turned out to hide far more than intended: on the "live"
database only 3 of 105 employees have an enabled Odoo login (most staff
don't need direct system access), so tying Portal User visibility to
login status collapsed Configuration -> Helpdesk Portal Users from 105
rows to 3, making it useless for managing Select Access for the rest of
the roster. Confirmed with the user: the Configuration list should track
active EMPLOYEES only (its original behavior); the stricter "must have
an active login" rule stays where it already correctly lived all along
-- client.helpdesk.ticket._get_assignable_users(), which drives the
"Assigned To" dropdown specifically.

active is back to a plain related field (employee_id.active), but the
stored column still holds 18.0.2.11.0's values, and a related field's
stored column isn't auto-resynced for existing rows on upgrade (same
class of gap as the compute-source change before it) -- force it here.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        UPDATE client_helpdesk_portal_user cpu
        SET active = he.active
        FROM hr_employee he
        WHERE he.id = cpu.employee_id
          AND cpu.active IS DISTINCT FROM he.active
    """)
