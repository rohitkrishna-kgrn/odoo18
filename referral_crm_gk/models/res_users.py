from lxml import etree

from odoo import Command, api, fields, models
from odoo.addons.base.models.res_users import name_selection_groups

# Lowest to highest: a user who still holds several roles shows the last one.
# Admin must stay last: it implies Manager, so every Admin also holds Manager.
REFERRAL_ROLES = [
    ('user', 'User', 'referral_crm_gk.group_referral_user'),
    ('accounts', 'Accounts', 'referral_crm_gk.group_referral_accounts'),
    ('manager', 'Manager', 'referral_crm_gk.group_referral_manager'),
    ('admin', 'Admin', 'referral_crm_gk.group_referral_admin'),
]
REFERRAL_CATEGORY = 'referral_crm_gk.module_category_referral'


class ResGroups(models.Model):
    _inherit = 'res.groups'

    @api.model
    def _update_user_groups_view(self):
        # The roles are picked with res.users.referral_role, shown in the
        # Sales block of the Access Rights tab, so the raw Referral checkboxes
        # are left out of the generated base.user_groups_view altogether,
        # debug mode included. The flag only filters the view generation: the
        # reified in_group_* fields still exist (_add_reified_groups does not
        # pass it). Never make the category a 'selection' here instead: that
        # puts a field into the stored view that only exists once this
        # module's Python is loaded, which breaks the upgrade of every module
        # that loads before this one.
        sales = next((gs for app, kind, gs, _cat in self.get_groups_by_application()
                      if app.xml_id == 'base.module_category_sales_sales' and kind == 'selection'), None)
        return super(ResGroups, self.with_context(
            referral_hide_role_groups=True,
            referral_sales_field=sales and name_selection_groups(sales.ids),
        ))._update_user_groups_view()

    @api.model
    def get_groups_by_application(self):
        res = super().get_groups_by_application()
        if self.env.context.get('referral_hide_role_groups'):
            res = [row for row in res if row[0].xml_id != REFERRAL_CATEGORY]
        return res


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def write(self, vals):
        # Give the generated Sales block name="sales_access", so
        # views/res_users_views.xml can anchor on it (inheritance may not
        # select on the translated string="Sales"). It has to happen inside
        # core's own write of base.user_groups_view: tagging afterwards fails,
        # because core first validates the untagged view against our
        # inherited view. Only an attribute is added, never a field, so this
        # is load-order safe. Core's placeholder view during installs has no
        # Sales block and is left alone.
        sales_field = self.env.context.get('referral_sales_field')
        if sales_field and isinstance(vals.get('arch'), str) and len(self) == 1 \
                and self == self.env.ref('base.user_groups_view', raise_if_not_found=False):
            arch = etree.fromstring(vals['arch'])
            nodes = arch.xpath("//group/field[@name=$name]/..", name=sales_field)
            if nodes:
                nodes[0].set('name', 'sales_access')
                vals = dict(vals, arch=etree.tostring(arch, pretty_print=True, encoding='unicode'))
        return super().write(vals)


class ResUsers(models.Model):
    _inherit = 'res.users'

    referral_role = fields.Selection(
        [(key, label) for key, label, _xmlid in REFERRAL_ROLES],
        string='Referral',
        compute='_compute_referral_role',
        inverse='_inverse_referral_role',
        groups='base.group_erp_manager',
    )

    def _referral_role_groups(self):
        return {key: self.env.ref(xmlid, raise_if_not_found=False) for key, _label, xmlid in REFERRAL_ROLES}

    @api.depends('groups_id')
    def _compute_referral_role(self):
        role_groups = self._referral_role_groups()
        for user in self:
            held = [key for key, group in role_groups.items() if group and group in user.groups_id]
            user.referral_role = held[-1] if held else False

    def _inverse_referral_role(self):
        role_groups = {key: group for key, group in self._referral_role_groups().items() if group}
        for user in self:
            commands = [Command.unlink(group.id) for group in role_groups.values()]
            if user.referral_role:
                commands.append(Command.link(role_groups[user.referral_role].id))
            user.groups_id = commands
