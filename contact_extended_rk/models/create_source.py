from odoo import api, models

PARTNER_FIELDS = ('partner_id', 'partner_invoice_id', 'partner_shipping_id')


def tag_partner_fields(arch, source, drop_prefill=False):
    """Stamp every contact picker in the view so a quick-create or
    "Create and edit" from it is recognised as coming from `source`."""
    stamp = "'partner_create_source': '%s'" % source
    for node in arch.iter('field'):
        if node.get('name') not in PARTNER_FIELDS:
            continue
        context = (node.get('context') or '{}').strip()
        if drop_prefill and node.get('name') == 'partner_id' and "'default_" in context:
            # The lead's name/address would pre-fill the Create Contact dialog.
            node.set('context', "{'res_partner_search_mode': type == 'opportunity' and 'customer' or False, %s}" % stamp)
            continue
        if not (context.startswith('{') and context.endswith('}')):
            continue
        inner = context[1:-1].strip()
        node.set('context', '{%s, %s}' % (stamp, inner) if inner else '{%s}' % stamp)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        tag_partner_fields(arch, 'crm', drop_prefill=True)
        return arch, view


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id, view_type, **options)
        tag_partner_fields(arch, 'services')
        return arch, view
