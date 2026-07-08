import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    v2.0.6: Independent commission payment status.

    The old `state` column (pending/partial/paid driven by invoice) is
    superseded by `commission_payment_status` (unpaid/paid, set only via
    the "Commission Paid" button).

    The old DB column is preserved by Odoo but no longer used. We populate
    `commission_payment_status` from it here so existing paid records
    carry over correctly.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Commissions previously fully paid → mark Paid
    cr.execute("""
        SELECT id, amount_paid, paid_date
        FROM referral_commission
        WHERE state = 'paid'
    """)
    paid_rows = cr.fetchall()
    for comm_id, old_amount_paid, old_paid_date in paid_rows:
        commission = env['referral.commission'].browse(comm_id)
        vals = {'commission_payment_status': 'paid'}
        if old_amount_paid and old_amount_paid > 0:
            vals['amount_paid'] = old_amount_paid
        if old_paid_date:
            vals['paid_date'] = old_paid_date
        commission.write(vals)

    # All other commissions (pending/partial) → Unpaid (already the default,
    # but set explicitly to be safe)
    cr.execute("""
        UPDATE referral_commission
        SET commission_payment_status = 'unpaid'
        WHERE state IN ('pending', 'partial')
    """)

    cr.execute("SELECT COUNT(*) FROM referral_commission WHERE state = 'paid'")
    paid_count = cr.fetchone()[0]
    cr.execute("SELECT COUNT(*) FROM referral_commission WHERE state IN ('pending', 'partial')")
    unpaid_count = cr.fetchone()[0]

    _logger.info(
        'referral_crm_gk v2.0.6 migration complete: '
        '%d commissions → Paid, %d commissions → Unpaid',
        paid_count, unpaid_count,
    )
