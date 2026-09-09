# -*- coding: utf-8 -*-
import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# The tags seeded by this module. Kept as the reference list for the initial
# clean-up only - the dropdown is driven by the `selectable` flag below, not
# by these names, so a Sales Administrator adding a thirteenth tag from
# Configuration gets a tag that actually works everywhere.
APPROVED_TAG_NAMES = [
    'SEO LANDLINE',
    'SEO EMAIL',
    'SEO WHATSAPP',
    'DIRECT',
    'KGRN',
    'REF BY CONSULTANT',
    'EXISTING CLIENT',
    'LOST',
    'ABSTRACT',
    'FREEZONE',
    'MAINLAND',
    'UNQUALIFIED LEAD',
]

APPROVED_TAG_DOMAIN = [('selectable', '=', True)]

# Set on every write the tag sync makes itself, so the hook on the receiving
# model returns instead of bouncing the same tags back and forth.
TAG_SYNC_CTX = 'crm_tag_sync'

_KEY_SEPARATORS = re.compile(r'[\s\-_/]+')


def log_tag_change(record, before, after, source=None):
    """Write a tag change into the record's own chatter.

    _message_log and not tracking=True on the field: a tracking message
    notifies the followers, and with every active user on email notifications
    and SMTP dead instance-wide, one tag edit spreading over a contact and its
    quotations would add dozens of failed mails to a queue already 5,600 deep.
    _message_log posts the note and notifies nobody.
    """
    added, removed = after - before, before - after
    if not added and not removed:
        return
    parts = []
    if added:
        parts.append(Markup("<b>added</b> %s") % ", ".join(added.mapped('display_name')))
    if removed:
        parts.append(Markup("<b>removed</b> %s") % ", ".join(removed.mapped('display_name')))
    detail = Markup(" &middot; ").join(parts)
    # `in` on a recordset raises across models, so compare the model first.
    from_elsewhere = source is not None and not (
        record._name == source._name and record in source)
    name = source.display_name if from_elsewhere and len(source) == 1 else None
    if name:
        body = Markup("Tags synced from %s &mdash; %s") % (name, detail)
    elif from_elsewhere:
        body = Markup("Tags synced &mdash; %s") % detail
    else:
        body = Markup("Tags updated &mdash; %s") % detail
    record.sudo()._message_log(body=body)


def tag_key(name):
    """Pairing key shared by a CRM tag and a contact tag.

    Case- and separator-insensitive on purpose: the CRM tag "DIRECT" has to
    pair with the contact tag "Direct" that 114 contacts already carry, rather
    than land beside it as a near-duplicate. Only ever used to pair the two the
    first time - the pairing is then stamped on res.partner.category.crm_tag_id
    and read from there, so renaming either side afterwards changes nothing.
    """
    return _KEY_SEPARATORS.sub(' ', (name or '').strip().lower())


class CrmTag(models.Model):
    _inherit = 'crm.tag'

    selectable = fields.Boolean(
        string='Selectable', default=True, index=True,
        help="Untick to keep a tag in the system but out of the Tags dropdown. "
             "Used for tags another module owns and assigns automatically, "
             "which nobody should be picking by hand.")

    @api.model_create_multi
    def create(self, vals_list):
        # The Tags dropdown offers no "Create" link, but that only covers the
        # dropdown. This closes the other routes - import, the API, a server
        # action - so only a Sales Administrator working in
        # CRM > Configuration > Tags can add one. Module data loading is
        # always allowed; that is how the approved tags arrived.
        if not (self.env.context.get('install_module')
                or self.env.su
                or self.env.user.has_group('sales_team.group_sale_manager')):
            raise UserError(_(
                "New tags can only be created by a Sales Administrator, "
                "from CRM > Configuration > Tags.\n\n"
                "Please pick one of the existing tags instead."))
        tags = super().create(vals_list)
        # A thirteenth tag has to reach the contact form too, so it gets its
        # paired contact tag straight away.
        tags._ensure_paired_categories()
        return tags

    def write(self, vals):
        res = super().write(vals)
        if 'selectable' in vals:
            self._ensure_paired_categories()
        return res

    # ------------------------------------------------------------------
    # Pairing with the contact tags (res.partner.category)
    #
    # Contacts keep their own Tags field, so a CRM tag reaches the contact
    # form as a res.partner.category of the same name. These helpers own the
    # correspondence in both directions; the sync itself lives on res.partner.
    # ------------------------------------------------------------------
    @api.model
    def _tags_for_categories(self, categories):
        """The selectable CRM tags meant by these contact tags."""
        categories = categories.sudo()
        tags = categories.crm_tag_id.filtered('selectable')
        unpaired = categories.filtered(lambda c: not c.crm_tag_id)
        if unpaired:
            by_key = {tag_key(t.name): t for t in self.sudo().search(APPROVED_TAG_DOMAIN)}
            for category in unpaired:
                match = by_key.get(tag_key(category.name))
                if match:
                    # Stamp the pairing the first time the names line up; from
                    # here on the link is by id and survives a rename.
                    category.crm_tag_id = match.id
                    tags |= match
        return tags

    @api.model
    def _canonical_category_map(self, tags, create=True):
        """{tag.id: category.id} - the contact tag the sync writes per CRM tag.

        Several spellings can mean one CRM tag ("SEO EMAIL" on 64 contacts and
        "SEO-EMAIL" on 11). Both read back as that tag, but only one is written
        going the other way, so the sync stops spreading the odd spelling.
        """
        Category = self.env['res.partner.category'].sudo()
        tags = tags.sudo()
        candidates = {}
        for category in Category.search([]):
            candidates.setdefault(category.crm_tag_id.id, Category)
            candidates[category.crm_tag_id.id] |= category
        by_key = {}
        for category in Category.search([('crm_tag_id', '=', False)]):
            by_key.setdefault(tag_key(category.name), Category)
            by_key[tag_key(category.name)] |= category

        mapping = {}
        for tag in tags:
            paired = candidates.get(tag.id) or by_key.get(tag_key(tag.name))
            if paired:
                category = self._canonical_category(tag, paired)
                if not category.crm_tag_id:
                    category.crm_tag_id = tag.id
            elif create:
                category = Category.create({'name': tag.name, 'crm_tag_id': tag.id})
            else:
                continue
            mapping[tag.id] = category.id
        return mapping

    @api.model
    def _canonical_category(self, tag, candidates):
        """Pick one contact tag out of several spellings of the same CRM tag."""
        if len(candidates) == 1:
            return candidates
        exact = candidates.filtered(lambda c: c.name == tag.name)
        if exact:
            return exact[0]
        self.env.cr.execute(
            """SELECT category_id, count(*) FROM res_partner_res_partner_category_rel
                WHERE category_id IN %s GROUP BY category_id""",
            (tuple(candidates.ids),))
        counts = dict(self.env.cr.fetchall())
        return candidates.sorted(lambda c: (-counts.get(c.id, 0), c.id))[0]

    @api.model
    def _categories_for_tags(self, tags, create=True):
        """The contact tags to write for these CRM tags."""
        mapping = self._canonical_category_map(tags, create=create)
        return self.env['res.partner.category'].sudo().browse(list(mapping.values()))

    def _ensure_paired_categories(self):
        """Give every selectable CRM tag a contact tag to travel as."""
        selectable = self.filtered('selectable')
        if selectable:
            self._canonical_category_map(selectable)


class ResPartnerCategory(models.Model):
    _inherit = 'res.partner.category'

    crm_tag_id = fields.Many2one(
        'crm.tag', string='CRM Tag', index=True, ondelete='set null', copy=False,
        help="The CRM tag this contact tag stands for. Set the first time the "
             "two are paired by name and read by id afterwards, so renaming "
             "either side cannot break the sync.")
