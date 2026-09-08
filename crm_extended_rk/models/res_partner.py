# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .crm_tag import TAG_SYNC_CTX, log_tag_change

_logger = logging.getLogger(__name__)

# Contacts pick from the CRM tag list and nothing else, so the Tags field only
# offers the contact tags paired with a CRM tag. Set on the field rather than
# per view, so the dropdown, the "Search: Tags" dialog and the search panel all
# obey it. Tags already on a contact still show - this restricts what can be
# picked, not what exists.
CRM_PAIRED_TAG_DOMAIN = [('crm_tag_id', '!=', False)]


class ResPartner(models.Model):
    _inherit = 'res.partner'

    category_id = fields.Many2many(domain=CRM_PAIRED_TAG_DOMAIN)

    def _crm_tags(self):
        """The CRM tags this contact's own Tags field stands for."""
        return self.env['crm.tag']._tags_for_categories(self.sudo().category_id)

    # ------------------------------------------------------------------
    # CRM tag sync: contact <-> its leads <-> its quotations
    #
    # Contacts keep their own Tags field, so a CRM tag travels as the
    # res.partner.category paired with it (see crm_tag._canonical_category_map).
    # ------------------------------------------------------------------
    def _apply_crm_tags(self, tags, source=None, mirror=True):
        """Make a contact, its leads and its quotations agree on one tag set.

        `mirror` is what an edit does: the tag set becomes exactly `tags`, so a
        tag removed on one record is removed on the others too and the three
        sides never drift. Only the CRM-paired tags are managed - unpaired
        contact tags (REFERENCE, the referral tags) and the non-selectable CRM
        tags another module assigns (DM) are left exactly as they are.

        `mirror=False` only adds, and is what a *new* record does: three
        modules create leads carrying a single source tag (web form, external
        feed, mail leads), and creating one of those must not wipe the client's
        other tags off every quotation it has.

        Runs as superuser: whoever edits the Tags on a contact is often not a
        salesperson, and the leads and quotations to update sit behind sales
        record rules they cannot read, let alone write.
        """
        if self.env.context.get(TAG_SYNC_CTX):
            return
        partners = self.sudo().filtered('id')
        tags = tags.sudo().filtered('selectable')
        if not partners or not (tags or mirror):
            return
        if mirror and not tags:
            # Every tag cleared off one record is a local removal, not an
            # instruction to strip the client and its whole quotation history.
            return
        Tag = self.env['crm.tag'].sudo()
        Lead = self.env['crm.lead'].sudo()
        Order = self.env['sale.order'].sudo()
        categories = Tag._categories_for_tags(tags)
        leads_by_partner = Lead.search([('partner_id', 'in', partners.ids)]).grouped('partner_id')
        orders_by_partner = Order.search([('partner_id', 'in', partners.ids)]).grouped('partner_id')

        for partner in partners:
            if partner != source:
                keep = partner.category_id.filtered(lambda c: not c.crm_tag_id) if mirror else partner.category_id
                self._set_tags_safely(partner, 'category_id', keep | categories, source)
            records = (list(leads_by_partner.get(partner, Lead))
                       + list(orders_by_partner.get(partner, Order)))
            for record in records:
                if source is not None and record in source:
                    continue
                keep = record.tag_ids.filtered(lambda t: not t.selectable) if mirror else record.tag_ids
                self._set_tags_safely(record, 'tag_ids', keep | tags, source)

    def _sync_crm_tags(self, mirror=True):
        """Push what the contact's own Tags field says onto its documents."""
        Tag = self.env['crm.tag'].sudo()
        for partner in self.sudo():
            partner._apply_crm_tags(Tag._tags_for_categories(partner.category_id),
                                    source=partner, mirror=mirror)

    @api.model
    def _apply_crm_tags_from(self, records, mirror=True):
        """Spread the tags of these leads or quotations to their contact."""
        for partner, group in records.grouped('partner_id').items():
            if partner:
                partner._apply_crm_tags(group.tag_ids, source=group, mirror=mirror)

    @api.model
    def _set_tags_safely(self, record, field, tags, source=None):
        """Write a tag set onto one linked record without ever failing the save.

        A linked record can refuse a write for reasons that have nothing to do
        with tags - two quotations carry an eInvoicing S6 line with no overage
        rate, and every write to them raises until someone fills it in.
        Blocking a contact edit over that would be absurd, so the record is
        skipped and logged. The savepoint keeps the failed write from poisoning
        the transaction the user is in.
        """
        before = record[field]
        if before == tags:
            return
        try:
            with self.env.cr.savepoint():
                record.with_context(**{TAG_SYNC_CTX: True}).write({
                    field: [(6, 0, tags.ids)],
                })
            log_tag_change(record, before, tags, source=source)
        except (UserError, ValidationError) as error:
            _logger.warning(
                "CRM tag sync could not tag %s (%s): %s",
                record.display_name, record._name, error)

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        tagged = partners.filtered('category_id')
        if tagged:
            tagged._sync_crm_tags(mirror=False)
        return partners

    def write(self, vals):
        syncing = self.env.context.get(TAG_SYNC_CTX)
        before = {p.id: p.category_id for p in self} if 'category_id' in vals and not syncing else {}
        res = super().write(vals)
        for partner in self:
            if partner.id in before:
                log_tag_change(partner, before[partner.id], partner.category_id)
        if 'category_id' in vals:
            self._sync_crm_tags()
        return res
