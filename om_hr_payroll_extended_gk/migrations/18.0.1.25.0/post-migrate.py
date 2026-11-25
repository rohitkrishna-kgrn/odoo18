import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Every company's (active) Quotation Approver User becomes a Payroll Admin."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].search([('approver_user_id', '!=', False)])
    added = companies._sync_payroll_admins()
    _logger.info("Quotation Approvers made Payroll Admin: %s", added.mapped('login'))
