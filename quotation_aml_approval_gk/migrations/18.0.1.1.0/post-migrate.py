import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Requests cancelled together with their quotation stop counting as
    AML/KYC Completed: flag them, then recompute the stored gate."""
    cr.execute("""
        UPDATE aml_request r SET cancelled_with_order = TRUE
          FROM sale_order so
         WHERE so.id = r.sale_order_id AND so.state = 'cancel'
           AND r.state = 'cancelled' AND r.cancelled_with_order IS NOT TRUE
     RETURNING r.name, so.name
    """)
    flagged = cr.fetchall()
    env = api.Environment(cr, SUPERUSER_ID, {})
    orders = env['aml.request'].search([('state', '=', 'cancelled')]).sale_order_id
    orders.invalidate_recordset(['aml_gate_completed'])
    orders._compute_aml_gate_completed()
    orders.flush_recordset(['aml_gate_completed'])
    _logger.info("quotation_aml_approval_gk 1.1.0: flagged %s cascade-cancelled request(s) %s; "
                 "recomputed AML/KYC Completed on %s", len(flagged), flagged, orders.mapped('name'))
