import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Approvers are now the Payroll 'Admin' access level. The active company Quotation
    Approvers (who approved payroll until now) become Payroll Admins so approval keeps
    working; batches waiting for approval are addressed to the Payroll Admins."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    admin_group = env.ref('om_hr_payroll_extended_gk.group_payroll_admin')
    approvers = env['res.company'].sudo().search([]).approver_user_id.filtered(lambda u: u.active and not u.share)
    for user in approvers - admin_group.users:
        user.write({'groups_id': [(4, admin_group.id)]})
        _logger.info("Payroll Admin given to %s (company Quotation Approver)", user.login)
    admins = env['res.users']._payroll_approvers()
    batches = env['payroll.country.batch'].search([('state', '=', 'submitted')])
    batches.write({'approver_user_ids': [(6, 0, admins.ids)]})
    env.registry.clear_cache()
