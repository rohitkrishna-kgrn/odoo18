from odoo import models

HR_DMS_GROUPS = ('hr_dms.group_hr_dms_employee', 'hr_dms.group_hr_dms_manager',
                 'hr_dms.group_hr_dms_admin', 'hr_dms.group_hr_dms_confidential')


def _watched_group_ids(env):
    ids = set()
    for xmlid in HR_DMS_GROUPS:
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            ids.add(group.id)
    return ids


class ResUsers(models.Model):
    _inherit = 'res.users'

    def write(self, vals):
        touches = any(k == 'groups_id' or k.startswith(('in_group_', 'sel_groups_')) for k in vals)
        if not touches:
            return super().write(vals)
        watched = _watched_group_ids(self.env)
        before = {u.id: set(u.sudo().groups_id.ids) & watched for u in self}
        res = super().write(vals)
        names = {g.id: g.name for g in self.env['res.groups'].sudo().browse(watched)}
        for user in self:
            now = set(user.sudo().groups_id.ids) & watched
            added, removed = now - before[user.id], before[user.id] - now
            if added or removed:
                self.env['hr.dms.audit.log'].log(
                    'access_change',
                    self.env._("User %(user)s - granted: %(add)s; revoked: %(rem)s",
                               user=user.sudo().name,
                               add=', '.join(names[i] for i in added) or '-',
                               rem=', '.join(names[i] for i in removed) or '-'),
                    confidential=bool(self.env.ref('hr_dms.group_hr_dms_confidential').id in (added | removed)))
        return res


class ResGroups(models.Model):
    _inherit = 'res.groups'

    def write(self, vals):
        if 'users' not in vals:
            return super().write(vals)
        watched = _watched_group_ids(self.env)
        mine = self.filtered(lambda g: g.id in watched)
        before = {g.id: set(g.sudo().users.ids) for g in mine}
        res = super().write(vals)
        for group in mine:
            now = set(group.sudo().users.ids)
            added, removed = now - before[group.id], before[group.id] - now
            if added or removed:
                users = self.env['res.users'].sudo().browse(added | removed)
                self.env['hr.dms.audit.log'].log(
                    'access_change',
                    self.env._("Group %(g)s - added: %(a)s; removed: %(r)s", g=group.name,
                               a=', '.join(self.env['res.users'].sudo().browse(added).mapped('name')) or '-',
                               r=', '.join(self.env['res.users'].sudo().browse(removed).mapped('name')) or '-'),
                    confidential=group == self.env.ref('hr_dms.group_hr_dms_confidential'))
        return res
