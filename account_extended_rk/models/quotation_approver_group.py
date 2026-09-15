from odoo import models, fields, api


class ResCompany(models.Model):
    """Keeps the Credit Hold Report access group in step with whichever
    user(s) are set as Quotation Approver.

    There is no dedicated "Quotation Approver" security group anywhere in
    this database -- sale_order_approval models the role as a single user per
    company (`approver_user_id`) instead. Rather than add a second,
    disconnected checkbox that somebody has to remember to tick (the original
    Credit Hold Managing Partner override group sat empty for exactly that
    reason until it was replaced), this keeps a real group's membership in
    lockstep with that field, across every company -- KGRN runs nine, and two
    different people are already set as approver on different ones.
    """
    _inherit = 'res.company'

    def write(self, vals):
        stale_users = self.env['res.users']
        if 'approver_user_id' in vals:
            stale_users = self.mapped('approver_user_id')
        res = super().write(vals)
        if 'approver_user_id' in vals:
            self.sudo()._sync_quotation_approver_group(stale_users)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        if any(vals.get('approver_user_id') for vals in vals_list):
            self.sudo()._sync_quotation_approver_group()
        return companies

    def _sync_quotation_approver_group(self, stale_users=None):
        """Recompute the group from scratch against every company's current
        `approver_user_id`, so a user who is still the approver on some other
        company is never dropped just because this one changed.
        """
        group = self.env.ref(
            'account_extended_rk.group_quotation_approver', raise_if_not_found=False)
        if not group:
            return
        current = self.env['res.company'].sudo().search([]).mapped('approver_user_id')
        no_longer_approver = (stale_users or self.env['res.users']) - current
        commands = [fields.Command.unlink(u.id) for u in no_longer_approver]
        commands += [fields.Command.link(u.id) for u in (current - group.sudo().users)]
        if commands:
            group.sudo().write({'users': commands})
