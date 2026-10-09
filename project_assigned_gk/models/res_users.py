from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Stored mirror of Employee > Manager, expressed as a user.  Record rules
    # traverse this field instead of hr.employee (which ordinary project users
    # cannot read) and, since it only needs `user.id`, the cached rule domain
    # never goes stale when someone's Manager changes.
    gk_manager_user_id = fields.Many2one(
        'res.users', string='Employee Manager (User)',
        compute='_compute_gk_manager_user_id', store=True, index=True,
        compute_sudo=True, readonly=True,
        help="User of the Manager set on this user's Employee form.")

    gk_is_project_manager = fields.Boolean(
        string='Project = Manager', compute='_compute_gk_is_project_manager',
        search='_search_gk_is_project_manager')

    def _compute_gk_is_project_manager(self):
        group = self.env.ref('project.group_project_manager')
        for user in self:
            user.gk_is_project_manager = group in user.sudo().groups_id

    def _search_gk_is_project_manager(self, operator, value):
        group = self.env.ref('project.group_project_manager')
        positive = (operator == '=') == bool(value)
        return [('groups_id', 'in' if positive else 'not in', group.id)]

    @api.depends('employee_ids.parent_id.user_id')
    def _compute_gk_manager_user_id(self):
        for user in self:
            managers = user.employee_ids.parent_id.user_id - user
            user.gk_manager_user_id = managers[:1]
