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

    # Every manager above this user (direct manager, their manager, ...).
    # Rules test `gk_manager_chain_ids in user.id`, so a manager sees direct
    # reports AND all subordinates below them, and nobody outside the branch.
    gk_manager_chain_ids = fields.Many2many(
        'res.users', 'res_users_gk_manager_chain_rel', 'user_id', 'manager_id',
        string='Management Chain', compute='_compute_gk_manager_chain_ids',
        store=True, compute_sudo=True, readonly=True,
        help="All users above this user in the Employee > Manager hierarchy.")

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

    @api.depends('gk_manager_user_id', 'gk_manager_user_id.gk_manager_chain_ids')
    def _compute_gk_manager_chain_ids(self):
        for user in self:
            chain = self.env['res.users']
            current = user.gk_manager_user_id
            # `current not in chain` guards against a loop in the hierarchy
            while current and current != user and current not in chain:
                chain |= current
                current = current.gk_manager_user_id
            user.gk_manager_chain_ids = chain
