"""client.helpdesk.portal.user.active changed from a plain related field
(employee_id.active only) to a stored compute that also considers
user_id.active, so a Portal User record disappears from Configuration
once its linked Odoo user is archived, not just its employee.

The 'active' column already exists (it was stored before too), so Odoo's
module-upgrade machinery does not detect that its computation source
changed and does not auto-recompute existing rows — confirmed on the
"live" database: all rows stayed active=True (the old related-field
value) until forced. Force it explicitly here.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    PortalUser = env['client.helpdesk.portal.user']
    recs = PortalUser.with_context(active_test=False).search([])
    recs._compute_active()
    env.flush_all()
