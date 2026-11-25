from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Bank details are no longer validated: re-run the checks of open lines so the
    saved "Bank details: ..." errors disappear."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.om_hr_payroll_extended_gk.models.payroll_line import EDITABLE_STATES
    env['payroll.country.line'].search([('batch_state', 'in', EDITABLE_STATES)])._validate()
