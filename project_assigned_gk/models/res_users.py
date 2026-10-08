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

    @api.depends('employee_ids.parent_id.user_id')
    def _compute_gk_manager_user_id(self):
        for user in self:
            managers = user.employee_ids.parent_id.user_id - user
            user.gk_manager_user_id = managers[:1]
