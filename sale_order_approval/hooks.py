# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def grant_product_management(env):
    """Grant product maintenance to whoever could already do it.

    The rule used to be "system administrators only". Moving it to a per-user
    checkbox would otherwise lock everyone out, so the users who held that
    right keep it and can hand it to others from the user form.

    Called from both the install hook and the 18.0.1.2 upgrade script: a
    post_init_hook runs on *install* only, so an installation that merely
    upgraded into this feature would otherwise be left with nobody able to
    touch products.
    """
    admins = env.ref('base.group_system').users.filtered(
        lambda user: not user.can_manage_products)
    admins.write({'can_manage_products': True})
    _logger.info(
        "sale_order_approval: granted 'Create / Edit Products' to %s existing "
        "administrator(s): %s", len(admins), ', '.join(admins.mapped('login')))
    return admins


def post_init_hook(env):
    grant_product_management(env)
