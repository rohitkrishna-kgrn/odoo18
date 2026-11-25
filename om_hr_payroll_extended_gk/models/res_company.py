from odoo import api, models

from .res_users import APPROVER_GROUP


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        if any(vals.get('approver_user_id') for vals in vals_list):
            companies._sync_payroll_admins()
        return companies

    def write(self, vals):
        res = super().write(vals)
        if 'approver_user_id' in vals:
            self._sync_payroll_admins()
        return res

    def _sync_payroll_admins(self):
        """A company's Quotation Approver User is a Payroll Admin by default (payroll
        approver). Only adds: Admins given by hand, or a former Quotation Approver, keep
        the access until it is changed on the user (Settings > Users > Payroll)."""
        users = self.sudo().mapped('approver_user_id').filtered(lambda u: u.active and not u.share)
        group = self.env.ref(APPROVER_GROUP).sudo()
        missing = users - group.users
        if missing:
            group.write({'users': [(4, uid) for uid in missing.ids]})
        # Country menus and record rules are cached per user
        self.env.registry.clear_cache()
        return missing
