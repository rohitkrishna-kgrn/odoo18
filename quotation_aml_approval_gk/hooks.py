import logging

_logger = logging.getLogger(__name__)


def _recompute_orders_with_cancelled_aml(env):
    """aml_gate_completed is stored. This module adds 'cancelled' to the
    states that tick it, but changing the rule never recomputes rows that
    already exist, so the orders it can affect are recomputed explicitly."""
    orders = env['aml.request'].sudo().search(
        [('state', '=', 'cancelled')]).sale_order_id
    if not orders:
        return orders
    orders.invalidate_recordset(['aml_gate_completed'])
    orders._compute_aml_gate_completed()
    orders.flush_recordset(['aml_gate_completed'])
    return orders


def post_init_hook(env):
    orders = _recompute_orders_with_cancelled_aml(env)
    _logger.info(
        "quotation_aml_approval_gk: recomputed AML/KYC Completed on %s order(s) "
        "with a cancelled AML request: %s",
        len(orders), ', '.join(orders.mapped('name')))


def uninstall_hook(env):
    # The registry still has this module's classes loaded here, so the
    # compute would keep counting 'cancelled'. Write the original rule back.
    orders = env['aml.request'].sudo().search(
        [('state', '=', 'cancelled')]).sale_order_id
    for order in orders:
        latest = order.aml_request_ids.sorted('create_date', reverse=True)[:1]
        env.cr.execute(
            "UPDATE sale_order SET aml_gate_completed = %s WHERE id = %s",
            (bool(latest) and latest.state in ('approved', 'bypassed'), order.id))
    orders.invalidate_recordset(['aml_gate_completed'])
