# -*- coding: utf-8 -*-
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
        return super().create(vals_list)
