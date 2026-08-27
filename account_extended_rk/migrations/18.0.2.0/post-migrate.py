"""Place the go-live credit hold backlog quietly.

When the 180-day credit hold policy was switched on there were already 615
customers carrying at least one posted invoice more than 180 days past due —
1,155 invoices, AED 4.99m outstanding. Running that backlog through the normal
path would have sent 615 separate hold notifications to every Project Manager
and sales team user attached to those customers in one morning, which is the
same trap the stale-draft policy avoided in 18.0.1.9.

So the backlog is placed in a single silent pass: every affected customer gets
Credit Hold = Yes, the full arrears snapshot, and a history event flagged
`is_backfill`, but no notification goes out. The restrictions on new projects
and proposals are live from this moment for all of them.

From the next nightly sweep onwards, holds and releases notify normally.
"""

import logging
from datetime import timedelta

from odoo import api, SUPERUSER_ID, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    cutoff = fields.Date.context_today(env['res.partner']) - timedelta(days=180)

    # active_test off to match _credit_hold_overdue_invoices: an archived
    # posted invoice is still money owed.
    overdue = env['account.move'].with_context(active_test=False).search([
        ('move_type', '=', 'out_invoice'),
        ('state', '=', 'posted'),
        ('payment_state', 'in', ('not_paid', 'partial')),
        ('invoice_date_due', '!=', False),
        ('invoice_date_due', '<', cutoff),
    ])
    partners = overdue.mapped('commercial_partner_id')
    if not partners:
        _logger.info("Credit hold backfill: no customers in arrears past 180 days.")
        return

    _logger.info(
        "Credit hold backfill: placing silent holds on %s customer(s) from %s "
        "overdue invoice(s).", len(partners), len(overdue),
    )

    # silent=True writes the flag, the arrears and the history event but sends
    # nothing. Batched so one bad record cannot roll back the whole pass.
    for index, partner in enumerate(partners, start=1):
        try:
            partner._credit_hold_evaluate(silent=True)
        except Exception:
            _logger.exception(
                "Credit hold backfill: skipped customer %s (id %s).",
                partner.display_name, partner.id,
            )
        if index % 100 == 0:
            _logger.info("Credit hold backfill: %s/%s", index, len(partners))

    held = env['res.partner'].search_count([('credit_hold', '=', True)])
    _logger.info("Credit hold backfill: %s customer(s) now on credit hold.", held)
