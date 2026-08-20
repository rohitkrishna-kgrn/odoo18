# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Backfill data that existing records need to satisfy the new rules.

    1. Every pipeline record gets its CRM reference, so quotations can cite one.
    2. Quotations already linked to an opportunity get the new CRM Pipeline
       field filled in, so the mandatory-link rule does not trip on records
       that were correctly linked before this module existed.
    """
    leads = env['crm.lead'].with_context(active_test=False).search(
        [('crm_ref', '=', False)], order='id')
    leads.action_assign_crm_ref()
    _logger.info("proposal_workflow_extended_rk: assigned %s CRM references", len(leads))

    orders = env['sale.order'].search(
        [('opportunity_id', '!=', False), ('crm_pipeline_id', '=', False)])
    for order in orders:
        order.crm_pipeline_id = order.opportunity_id
    _logger.info(
        "proposal_workflow_extended_rk: linked %s existing orders to their pipeline record",
        len(orders))

    # 3. Someone has to be able to open the dashboard on day one; administrators
    #    get it and can then tick the box for anyone else.
    for xmlid in ('proposal_workflow_extended_rk.group_einvoicing_dashboard',
                  'proposal_workflow_extended_rk.group_other_services_dashboard'):
        dashboard_group = env.ref(xmlid, raise_if_not_found=False)
        if not dashboard_group:
            continue
        admins = env.ref('base.group_system').users.filtered(
            lambda user: dashboard_group not in user.groups_id)
        admins.write({'groups_id': [(4, dashboard_group.id)]})
        _logger.info("proposal_workflow_extended_rk: granted %s to %s administrator(s)",
                     dashboard_group.name, len(admins))
