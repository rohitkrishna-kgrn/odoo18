from odoo import _, api, fields, models

# Payroll dropdown on the user (om_hr_payroll category "Payroll"): Officer -> Manager -> Admin
OFFICER_GROUP = 'om_hr_payroll.group_hr_payroll_user'
MANAGER_GROUP = 'om_hr_payroll.group_hr_payroll_manager'
APPROVER_GROUP = 'om_hr_payroll_extended_gk.group_payroll_admin'


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Not used since 18.0.1.17.0: an officer's country is their own Leave Location. Kept so
    # no view of another module that might still name it breaks.
    payroll_country_ids = fields.Many2many(
        'res.country', 'res_users_payroll_country_rel', 'user_id', 'country_id',
        string='Allowed Payroll Countries (unused)')
    payroll_restricted_location = fields.Char(
        compute='_compute_payroll_restricted_location',
        help="Leave Location that limits this user's Employees / Contracts (Payroll Officer only); "
             "empty = not limited. Read by the global employee / contract record rules.")

    @api.depends_context('uid')
    def _compute_payroll_restricted_location(self):
        for user in self:
            restricted = (user.country and user.has_group(OFFICER_GROUP)
                          and not user.has_group(MANAGER_GROUP)
                          and not user.has_group('hr.group_hr_manager'))
            user.payroll_restricted_location = user.country if restricted else False

    def _is_payroll_manager(self):
        """Payroll Manager or Admin: every country."""
        self.ensure_one()
        return self.has_group(MANAGER_GROUP)

    def _is_payroll_officer(self):
        self.ensure_one()
        return self.has_group(OFFICER_GROUP)

    def _is_payroll_approver(self):
        """Payroll Admin: the only users who approve / reject / ask for resubmission."""
        self.ensure_one()
        return self.has_group(APPROVER_GROUP)

    def _payroll_allowed_countries(self):
        """res.country records this user may run payroll for: Manager / Admin every
        country, an Officer only the payroll whose Leave Location is their own."""
        self.ensure_one()
        configs = self.env['payroll.country'].sudo().search([])
        if self._is_payroll_manager():
            return configs.country_id
        if self._is_payroll_officer() and self.country:
            return configs.filtered(lambda c: c.leave_location == self.country).country_id
        return self.env['res.country']

    def _payroll_user_archived(self):
        """An archived user's employees leave payroll: their contracts are archived and
        they are removed from every open payroll batch."""
        employees = self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('user_id', 'in', self.ids)])
        if not employees:
            return
        contracts = self.env['hr.contract'].sudo().search([('employee_id', 'in', employees.ids)])
        if contracts:
            contracts.write({'active': False})
        self.env['payroll.country.batch']._drop_archived_employees(employees, _("User is archived"))

    @api.model
    def _payroll_approvers(self):
        group = self.env.ref(APPROVER_GROUP)
        return self.sudo().search([('groups_id', 'in', group.id), ('share', '=', False)])

    def write(self, vals):
        archiving = 'active' in vals and not vals['active']
        res = super().write(vals)
        if archiving:
            self._payroll_user_archived()
        if 'country' in vals or any(k.startswith('in_group_') or k.startswith('sel_groups_')
                                    or k == 'groups_id' for k in vals):
            # Country menus (ir.ui.menu.load_menus) and the record rules on Leave Location are
            # cached per user: a new Leave Location or access level must show at once.
            self.env.registry.clear_cache()
        return res
