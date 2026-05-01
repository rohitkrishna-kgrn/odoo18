from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    task_transfer_user = fields.Boolean(
        string='Task Transfer User',
        compute='_compute_task_transfer_user',
        inverse='_set_task_transfer_user',
        store=False,
    )

    def _compute_task_transfer_user(self):
        group = self.env.ref('task_transfer_rk.group_task_transfer_user')
        for user in self:
            user.task_transfer_user = group.id in user.groups_id.ids

    def _set_task_transfer_user(self):
        group = self.env.ref('task_transfer_rk.group_task_transfer_user')
        for user in self:
            if user.task_transfer_user:
                user.sudo().write({'groups_id': [(4, group.id)]})
            else:
                user.sudo().write({'groups_id': [(3, group.id)]})
