import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Only employees with an active user are in payroll (user's decision 2026-11-24:
    apply to everyone now). Every archived user's employees get their contracts archived
    and leave the open payroll batches; approved batches are not changed."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    users = env['res.users'].with_context(active_test=False).search([('active', '=', False)])
    employees = env['hr.employee'].with_context(active_test=False).search([('user_id', 'in', users.ids)])
    contracts = env['hr.contract'].search([('employee_id', 'in', employees.ids)])
    lines = env['payroll.country.line'].search([('employee_id', 'in', employees.ids),
                                                ('batch_state', 'in', ('draft', 'calculated', 'rejected', 'resubmit'))])
    _logger.info("archived users: %s employees, %s contracts archived, %s open payroll lines removed",
                 len(employees), len(contracts), len(lines))
    users._payroll_user_archived()
