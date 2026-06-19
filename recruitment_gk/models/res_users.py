from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    # ── Recruitment access boolean fields ──────────────────────────────────
    # Each field reflects membership in the corresponding group.
    # Setting True/False adds/removes the user from that group.

    recruitment_is_management = fields.Boolean(
        string='Management Admin',
        compute='_compute_recruitment_groups',
        inverse='_set_recruitment_management',
        store=False,
    )
    recruitment_is_hr_admin = fields.Boolean(
        string='HR Admin',
        compute='_compute_recruitment_groups',
        inverse='_set_recruitment_hr_admin',
        store=False,
    )
    recruitment_is_hiring_manager = fields.Boolean(
        string='Hiring Manager',
        compute='_compute_recruitment_groups',
        inverse='_set_recruitment_hiring_manager',
        store=False,
    )
    recruitment_is_it_team = fields.Boolean(
        string='IT Team',
        compute='_compute_recruitment_groups',
        inverse='_set_recruitment_it_team',
        store=False,
    )

    def _get_recruitment_group(self, xml_id):
        return self.env.ref('recruitment_gk.%s' % xml_id, raise_if_not_found=False)

    @api.depends('groups_id')
    def _compute_recruitment_groups(self):
        mgmt = self._get_recruitment_group('group_recruitment_management')
        hr = self._get_recruitment_group('group_recruitment_hr_admin')
        hm = self._get_recruitment_group('group_recruitment_hiring_manager')
        it = self._get_recruitment_group('group_recruitment_it_team')
        for user in self:
            user.recruitment_is_management = bool(mgmt and mgmt in user.groups_id)
            user.recruitment_is_hr_admin = bool(hr and hr in user.groups_id)
            user.recruitment_is_hiring_manager = bool(hm and hm in user.groups_id)
            user.recruitment_is_it_team = bool(it and it in user.groups_id)

    def _set_recruitment_management(self):
        self._toggle_recruitment_group('group_recruitment_management', self.recruitment_is_management)

    def _set_recruitment_hr_admin(self):
        self._toggle_recruitment_group('group_recruitment_hr_admin', self.recruitment_is_hr_admin)

    def _set_recruitment_hiring_manager(self):
        self._toggle_recruitment_group('group_recruitment_hiring_manager', self.recruitment_is_hiring_manager)

    def _set_recruitment_it_team(self):
        self._toggle_recruitment_group('group_recruitment_it_team', self.recruitment_is_it_team)

    def _toggle_recruitment_group(self, xml_id, add):
        group = self._get_recruitment_group(xml_id)
        if not group:
            return
        for user in self:
            if add:
                user.sudo().write({'groups_id': [(4, group.id)]})
            else:
                user.sudo().write({'groups_id': [(3, group.id)]})
