# -*- coding: utf-8 -*-
"""Pair the CRM tags with the contact tags, then backfill in every direction.

CRM tags now reach the contact form as res.partner.category records, and the
three sides - contact, its leads, its quotations - hold one union of tags.
This is the one-off catch-up for the records that already exist; from here on
the create/write hooks keep them in step.

Done in SQL on purpose: the alternative is a few thousand ORM writes whose
side effects (chatter, mail, quotation hooks) have nothing to do with a tag
backfill.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.crm_extended_rk.models.crm_tag import APPROVED_TAG_DOMAIN, tag_key

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    tags = env['crm.tag'].search(APPROVED_TAG_DOMAIN)
    if not tags:
        return

    # 1. One contact tag per CRM tag, reusing what contacts already carry
    #    ("Direct" for DIRECT) and creating the rest.
    canonical = env['crm.tag']._canonical_category_map(tags)

    # 2. Pair the other spellings too ("SEO-EMAIL" -> SEO EMAIL), so a contact
    #    carrying one of those still reads as that CRM tag.
    by_key = {tag_key(tag.name): tag for tag in tags}
    variants = env['res.partner.category'].search([('crm_tag_id', '=', False)])
    for category in variants:
        match = by_key.get(tag_key(category.name))
        if match:
            category.crm_tag_id = match.id
    env.flush_all()

    # 3. The union of tags per contact, from its own tags, its leads and its
    #    quotations - then written back to all three.
    union = """
        WITH selectable AS (SELECT id FROM crm_tag WHERE selectable),
             pair AS (SELECT id AS category_id, crm_tag_id AS tag_id
                        FROM res_partner_category WHERE crm_tag_id IS NOT NULL),
             union_tags AS (
                 SELECT rel.partner_id, pair.tag_id
                   FROM res_partner_res_partner_category_rel rel
                   JOIN pair ON pair.category_id = rel.category_id
                 UNION
                 SELECT lead.partner_id, rel.tag_id
                   FROM crm_lead lead
                   JOIN crm_tag_rel rel ON rel.lead_id = lead.id
                   JOIN selectable ON selectable.id = rel.tag_id
                  WHERE lead.partner_id IS NOT NULL
                 UNION
                 SELECT so.partner_id, rel.tag_id
                   FROM sale_order so
                   JOIN sale_order_tag_rel rel ON rel.order_id = so.id
                   JOIN selectable ON selectable.id = rel.tag_id
             )
    """

    cr.execute(union + """
        INSERT INTO crm_tag_rel (lead_id, tag_id)
        SELECT lead.id, union_tags.tag_id
          FROM crm_lead lead
          JOIN union_tags ON union_tags.partner_id = lead.partner_id
        EXCEPT SELECT lead_id, tag_id FROM crm_tag_rel
    """)
    leads_done = cr.rowcount

    cr.execute(union + """
        INSERT INTO sale_order_tag_rel (order_id, tag_id)
        SELECT so.id, union_tags.tag_id
          FROM sale_order so
          JOIN union_tags ON union_tags.partner_id = so.partner_id
        EXCEPT SELECT order_id, tag_id FROM sale_order_tag_rel
    """)
    orders_done = cr.rowcount

    # Contacts get the canonical spelling only, never the variants.
    cr.execute(union + """
        INSERT INTO res_partner_res_partner_category_rel (partner_id, category_id)
        SELECT union_tags.partner_id, canonical.category_id
          FROM union_tags
          JOIN (VALUES %s) AS canonical(tag_id, category_id)
            ON canonical.tag_id = union_tags.tag_id
        EXCEPT SELECT partner_id, category_id
                 FROM res_partner_res_partner_category_rel
    """ % ', '.join('(%d, %d)' % pair for pair in canonical.items()))
    partners_done = cr.rowcount

    env.invalidate_all()
    _logger.info(
        "CRM tag sync backfill: %s lead tags, %s quotation tags, %s contact tags added "
        "across %s paired tags.", leads_done, orders_done, partners_done, len(canonical))
