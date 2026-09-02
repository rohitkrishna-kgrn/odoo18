import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Recover the AP deliveries the unscoped instance-id lookup swallowed.

    Until this version ``_einv_find_received`` searched every move type for the
    delivered instance id. A Peppol transmission carries one instance id for
    both legs and we stamp it on the customer invoice at clearance, so a
    document that came back to our own webhook matched that invoice and was
    acked as "unchanged" — the vendor bill was never created. The platform
    treats its 2xx as final and never re-sends, so fixing the lookup alone
    leaves the already-delivered documents permanently missing from Bills.

    The webhook body is stored verbatim on einvoice.log, which makes the
    delivery replayable. The replay is idempotent, so re-running this upgrade
    is harmless.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    recovered = env['account.move']._einv_replay_swallowed_ap()
    _logger.info(
        'einvoicing_extended_rk: recovered %s vendor bill(s) from swallowed AP '
        'deliveries: %s',
        len(recovered), ', '.join(recovered.mapped('ref')) or 'none',
    )
