"""Credit Hold Report: seed the Quotation Approver access group.

The group (account_extended_rk.group_quotation_approver) is kept in sync
with res.company.approver_user_id going forward by the write() override in
models/quotation_approver_group.py -- but that only fires on a *future*
change to the field. The companies that already have an approver configured
never trigger a write during this upgrade, so without this one-off pass the
Credit Hold Report menu would be invisible to everyone, including the people
who are supposed to see it, until somebody happened to re-save a company
record.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    companies = env['res.company'].search([])
    companies._sync_quotation_approver_group()

    group = env.ref('account_extended_rk.group_quotation_approver', raise_if_not_found=False)
    _logger.info(
        "Quotation Approver group seeded with %s user(s): %s",
        len(group.users) if group else 0,
        ', '.join(group.users.mapped('login')) if group else '',
    )
