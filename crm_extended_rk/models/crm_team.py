from odoo import api, models


class CrmTeam(models.Model):
    _inherit = 'crm.team'

    # The sale.order search view carries one Filters entry per team, built at
    # view-render time by SaleOrder._get_view(). That result is held in the
    # 'templates' ormcache, which Odoo only drops when an ir.ui.view changes -
    # so without the invalidation below a team created, renamed, archived or
    # deleted in Configuration > Sales Teams would not reach the Filters
    # dropdown until the next server restart or module upgrade.

    def _invalidate_sale_order_search_view(self):
        self.env.registry.clear_cache('templates')

    @api.model_create_multi
    def create(self, vals_list):
        teams = super().create(vals_list)
        teams._invalidate_sale_order_search_view()
        return teams

    def write(self, vals):
        res = super().write(vals)
        # Only the label and whether the team is listed at all are baked into
        # the view; the rest of a team's fields are irrelevant to it.
        if 'name' in vals or 'active' in vals:
            self._invalidate_sale_order_search_view()
        return res

    def unlink(self):
        res = super().unlink()
        self._invalidate_sale_order_search_view()
        return res
