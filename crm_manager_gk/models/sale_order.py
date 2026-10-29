from odoo import api, models
from odoo.osv import expression


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        # The Services menus pass own_created_quotations_only, and
        # crm_extended_rk then narrows "User: Own Documents Only" salespeople to
        # user_id = me.  A CRM Manager gets their whole reporting hierarchy
        # instead: widen the domain here and switch the key off so
        # crm_extended_rk does not narrow it straight back.  Same scope as
        # rule_crm_manager_sale_order.
        if self.env.context.get('own_created_quotations_only') and not self.env.su:
            user = self.env.user
            if (user.has_group('crm_manager_gk.group_crm_manager')
                    and user.has_group('sales_team.group_sale_salesman')
                    and not user.has_group('sales_team.group_sale_salesman_all_leads')):
                domain = expression.AND([
                    ['|', ('user_id', '=', user.id), ('user_id.gk_manager_chain_ids', 'in', [user.id])],
                    list(domain or []),
                ])
                widened = self.with_context(own_created_quotations_only=False)
                return super(SaleOrder, widened)._search(
                    domain, offset=offset, limit=limit, order=order, **kwargs)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
