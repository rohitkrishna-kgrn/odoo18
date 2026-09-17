# -*- coding: utf-8 -*-
"""Carry Sales Managers' Mail Leads access over from implied_ids to a plain seed.

The "Mail Leads" checkbox on the user form used to be permanently tied to
Sales Manager via implied_ids. That link is a hard implication, not a
default: as long as a user is still checked as Sales Manager, Odoo's
reified-group write always re-adds the implied group, so unchecking "Mail
Leads" for a manager silently reverted itself on save. The link has been
dropped in favour of plain group membership, which the user form can freely
grant or revoke per user. This is the one-off carry-over so no Sales Manager
loses the access they already had at the moment of the switch.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    mail_lead_group = env.ref('crm_mail_lead_rk.group_crm_mail_lead_user')
    sales_managers = env.ref('sales_team.group_sale_manager').users
    to_add = sales_managers - mail_lead_group.users
    if to_add:
        mail_lead_group.write({'users': [(4, user.id) for user in to_add]})
