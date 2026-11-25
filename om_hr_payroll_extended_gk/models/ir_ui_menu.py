from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        """Dubai / India Payroll menus: a Payroll Officer sees only the payroll of their own
        Leave Location; Managers / Admins see every country.
        (Display only - access itself is enforced by record rules.)"""
        res = super()._load_menus_blacklist()
        user = self.env.user
        if user._is_payroll_manager():
            return res
        allowed = user._payroll_allowed_countries()
        hidden = [config.menu_id.id
                  for config in self.env['payroll.country'].sudo().with_context(active_test=False).search([])
                  if config.menu_id and config.country_id not in allowed]
        return list(res) + hidden
