import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    v2.0.8: Commission now calculated on sale order untaxed amount (excl. VAT).

    Recompute x_deal_value and x_commission_amount for all referral leads that
    have a linked sale order so the stored values reflect the new formula.
    The commission records (referral.commission) will pick up the new values
    automatically via their related fields.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    leads = env['crm.lead'].search([
        ('x_is_referral', '=', True),
        ('x_sale_order_id', '!=', False),
    ])
    if leads:
        leads._compute_deal_value()
        leads._compute_commission()
        _logger.info(
            'referral_crm_gk v2.0.8: recomputed deal value and commission '
            'for %d referral leads (now using untaxed amount, excl. VAT)',
            len(leads),
        )
    else:
        _logger.info('referral_crm_gk v2.0.8: no referral leads with sale orders to recompute')
