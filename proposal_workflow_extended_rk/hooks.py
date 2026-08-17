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
