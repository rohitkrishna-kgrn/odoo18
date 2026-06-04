from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    mis_role = fields.Selection(
        selection=[
            ('user', 'MIS User'),
            ('manager', 'MIS Manager'),
            ('admin', 'MIS Admin'),
        ],
        string='MIS Role',
        compute='_compute_mis_role',
        inverse='_set_mis_role',
    )

    @api.depends('groups_id')
    def _compute_mis_role(self):
        admin_grp = self.env.ref('mis_report_kgrn.group_mis_admin', raise_if_not_found=False)
        mgr_grp = self.env.ref('mis_report_kgrn.group_mis_manager', raise_if_not_found=False)
        user_grp = self.env.ref('mis_report_kgrn.group_mis_user', raise_if_not_found=False)
        for user in self:
            if admin_grp and admin_grp in user.groups_id:
                user.mis_role = 'admin'
            elif mgr_grp and mgr_grp in user.groups_id:
                user.mis_role = 'manager'
            elif user_grp and user_grp in user.groups_id:
                user.mis_role = 'user'
            else:
                user.mis_role = False

    def _set_mis_role(self):
        admin_grp = self.env.ref('mis_report_kgrn.group_mis_admin', raise_if_not_found=False)
        mgr_grp = self.env.ref('mis_report_kgrn.group_mis_manager', raise_if_not_found=False)
        user_grp = self.env.ref('mis_report_kgrn.group_mis_user', raise_if_not_found=False)

        remove_cmds = []
        for grp in (admin_grp, mgr_grp, user_grp):
            if grp:
                remove_cmds.append((3, grp.id))

        for user in self:
            if remove_cmds:
                user.sudo().write({'groups_id': remove_cmds})
            role_map = {
                'admin': admin_grp,
                'manager': mgr_grp,
                'user': user_grp,
            }
            target_grp = role_map.get(user.mis_role)
            if target_grp:
                user.sudo().write({'groups_id': [(4, target_grp.id)]})
