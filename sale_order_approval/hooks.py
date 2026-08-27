# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Grant product maintenance to whoever could already do it.

    The rule used to be "system administrators only". Moving it to a per-user
    checkbox would otherwise lock everyone out on upgrade, so the users who held
    that right keep it and can hand it to others from the user form.
    """
    admins = env.ref('base.group_system').users.filtered(
        lambda user: not user.can_manage_products)
    admins.write({'can_manage_products': True})
    _logger.info(
        "sale_order_approval: granted 'Create / Edit Products' to %s existing "
        "administrator(s): %s", len(admins), ', '.join(admins.mapped('login')))
