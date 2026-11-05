import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    v2.0.11: Referrals now run on the CRM / Services flow (crm_extended_rk).

    - Referral leads become opportunities, so they show in the CRM pipeline
      and get the standard New Quotation button.
    - The 29 service tags this module seeded are hidden from the CRM tag
      dropdown (CRM tags classify the lead source). Their names move into
      x_referral_services and the lead gets REF BY CONSULTANT instead.
    - Quotations already raised on a referral opportunity get linked.
    The tag records themselves are kept (noupdate data, contacts carry them).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Lead = env['crm.lead'].with_context(active_test=False, tracking_disable=True)

    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'referral_crm_gk' AND model = 'crm.tag'
    """)
    service_tags = env['crm.tag'].browse([r[0] for r in cr.fetchall()]).exists()
    ref_tag = env.ref('crm_extended_rk.quotation_tag_ref_by_consultant', raise_if_not_found=False)

    leads = Lead.search([('x_is_referral', '=', True)])
    for lead in leads:
        vals = {}
        if lead.type != 'opportunity':
            vals['type'] = 'opportunity'
        services = lead.tag_ids & service_tags
        if services:
            if not lead.x_referral_services:
                vals['x_referral_services'] = ', '.join(services.mapped('name'))
            vals['tag_ids'] = [(3, t.id) for t in services]
        if ref_tag and ref_tag not in lead.tag_ids:
            vals.setdefault('tag_ids', []).append((4, ref_tag.id))
        if vals:
            lead.write(vals)

    # Only after reading the leads: crm_extended_rk puts a selectable=True
    # domain on tag_ids, so a hidden tag no longer shows in lead.tag_ids.
    if 'selectable' in service_tags._fields:
        service_tags.write({'selectable': False})

    orders = env['sale.order'].search([('opportunity_id', 'in', leads.ids)], order='id')
    for order in orders:
        lead = order.opportunity_id
        order.x_referral_lead_id = lead.id
        if order.state == 'sale' or not lead.x_sale_order_id:
            lead.x_sale_order_id = order.id

    _logger.info(
        'referral_crm_gk v2.0.11: %d referral leads moved onto the CRM flow, '
        '%d service tags hidden, %d quotations linked',
        len(leads), len(service_tags), len(orders),
    )
