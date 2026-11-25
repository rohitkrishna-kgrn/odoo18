import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """PF / ESI are for India employees only: flag every line, and recalculate open
    non-India lines that still carry an EPF / ESI amount."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.om_hr_payroll_extended_gk.models.payroll_line import EDITABLE_STATES
    lines = env['payroll.country.line'].search([])
    for line in lines:
        applies = line.employee_id.with_context(active_test=False).country_for_leave == 'india'
        line._system_write({'pf_esi_applies': applies})
        if not applies and line.batch_state in EDITABLE_STATES and (line.epf or line.esi or line.calc_epf
                                                                      or line.calc_esi or line.pf_wage):
            if line.payslip_id:
                line._calculate()
            line._validate()
            _logger.info("payroll line %s (%s): PF / ESI removed (not an India employee)", line.id, line.employee_name)
