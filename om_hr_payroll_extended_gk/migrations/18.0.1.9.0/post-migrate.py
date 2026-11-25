import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Employee / contract / bank values now always match the Employee and the Contract.
    Values typed on open lines before 1.9.0 were per-payroll overrides: they are dropped
    (still listed in the line's change log) and the line re-reads the source."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['payroll.country.line']
    from odoo.addons.om_hr_payroll_extended_gk.models.payroll_line import EDITABLE_STATES, SYNC_FIELDS
    lines = Line.search([('batch_state', 'in', EDITABLE_STATES), ('manual_keys', '!=', ',')])
    for line in lines:
        manual = line._manual()
        dropped = manual & set(SYNC_FIELDS)
        if not dropped:
            continue
        keep = manual - dropped
        line._system_write({'manual_keys': ',' + ','.join(sorted(keep)) + (',' if keep else '')})
        line._refresh_snapshot()
        if line.payslip_id:
            line._calculate()
        line._validate()
        _logger.info("payroll line %s (%s): typed %s dropped, now follows the employee / contract",
                     line.id, line.employee_name, ', '.join(sorted(dropped)))
