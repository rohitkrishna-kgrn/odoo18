from odoo import models, fields, api
from odoo.osv import expression


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


    # ── Scope mapping: who does this user supervise? ──────────────────────
    # Two independent assignments on the employee form drive every MIS
    # visibility decision. Neither is a custom field — both are stock Odoo:
    #
    #   * Coach   (hr.employee.coach_id)  -> mis_coachee_uids
    #   * Manager (hr.employee.parent_id) -> mis_report_uids
    #
    # There is deliberately NO "MIS Coach" group any more. Being somebody's
    # coach is a property of the employee record, not a permission: it widens
    # what an existing MIS role can see, and grants nothing on its own. A
    # coach with no MIS role sees no MIS menus at all, exactly like any other
    # employee.
    #
    # Both are fields.Json holding a plain list of user ids, after two other
    # shapes failed:
    #   * Many2one/Many2many('res.users') on res.users is self-referencing and
    #     does not keep what its compute assigns (it read back one unrelated
    #     id).
    #   * hr.employee.coach_id's reverse, read as
    #     user.employee_ids[:1].mis_coachee_ids.user_id.ids, raises
    #     "not available for employee public profiles" for any coach without
    #     HR rights — which is most of them. (child_ids works in the older
    #     manager rules only because it is a *public* employee field; a custom
    #     o2m is not.) The computes below do their hr.employee lookups under
    #     sudo, so the reader's HR rights never come into it.
    #
    # All three are non-stored computes read straight from ir.rule
    # domain_force. ir.rule._compute_domain is ormcached per user and bakes
    # the resulting id lists into the cached domain, so any change to
    # coach_id/parent_id must clear the registry cache — see
    # HrEmployee._mis_clear_scope_cache in models/mis_employee.py.
    mis_coachee_uids = fields.Json(
        string='Coachee User Ids',
        compute='_compute_mis_scope_uids',
        help="User ids of the employees who have this user set as their "
             "Coach on the employee form. Empty for anyone who coaches "
             "nobody. Read by the MIS record rules.",
    )
    mis_report_uids = fields.Json(
        string='Direct Report User Ids',
        compute='_compute_mis_scope_uids',
        help="User ids of the employees who have this user set as their "
             "Manager on the employee form. Empty for anyone with no direct "
             "reports. Read by the MIS record rules.",
    )
    mis_scope_uids = fields.Json(
        string='Supervised User Ids',
        compute='_compute_mis_scope_uids',
        help="Direct reports and coachees merged into one de-duplicated "
             "list, excluding the user themselves. Somebody who is both a "
             "direct report and a coachee appears exactly once.",
    )

    def _compute_mis_scope_uids(self):
        Employee = self.env['hr.employee'].sudo()
        for user in self:
            # sudo: coach_id/parent_id sit behind hr.employee's access rules,
            # and a coach or line manager is typically a plain internal user
            # with no HR rights at all.
            emp = Employee.search([('user_id', '=', user.id)], limit=1)
            if not emp:
                user.mis_coachee_uids = []
                user.mis_report_uids = []
                user.mis_scope_uids = []
                continue
            coachees = Employee.search([
                ('coach_id', '=', emp.id),
                ('user_id', '!=', False),
            ]).mapped('user_id').ids
            reports = Employee.search([
                ('parent_id', '=', emp.id),
                ('user_id', '!=', False),
            ]).mapped('user_id').ids
            user.mis_coachee_uids = coachees
            user.mis_report_uids = reports
            # dict.fromkeys de-duplicates while keeping a stable order: an
            # employee who is both this user's direct report AND their
            # coachee must be listed once, not twice.
            user.mis_scope_uids = [
                uid for uid in dict.fromkeys(reports + coachees)
                if uid != user.id
            ]

    def _mis_access_domain(self, manager_field='project_manager_id',
                           salesperson_field=None):
        """The OR of every ir.rule term that applies to this user on one of
        the project-based MIS reports.

        Kept deliberately in lockstep with rule_mis_*_user / _manager /
        _admin in security/ir_rules.xml. The record rules are what actually
        filter the OWL grid (search_read goes through search_fetch and never
        calls search()); this is the same boundary re-stated for the
        search/search_count/read_group paths, so no route can be looser OR
        tighter than another.

        `salesperson_field` is passed only by the reports that carry one —
        mis.project.revenue is task-level and has no salesperson column.
        """
        self.ensure_one()
        if self.has_group('mis_report_kgrn.group_mis_admin'):
            return []
        # Every non-admin role starts from the plain MIS User rule.
        if salesperson_field:
            terms = [['|', (manager_field, '=', self.id),
                      (salesperson_field, '=', self.id)]]
        else:
            terms = [[(manager_field, '=', self.id)]]
        # Manager field on the employee form — MIS Managers only.
        if self.has_group('mis_report_kgrn.group_mis_manager') and self.mis_report_uids:
            terms.append([(manager_field, 'in', self.mis_report_uids)])
        # Coach field on the employee form — applies to every MIS role,
        # exactly as rule_mis_*_user does via the implied-group chain.
        if self.mis_coachee_uids:
            terms.append([(manager_field, 'in', self.mis_coachee_uids)])
        return expression.OR(terms) if len(terms) > 1 else terms[0]

    # ── One-time migration off the removed MIS Coach group ────────────────
    @api.model
    def _mis_migrate_coach_group(self):
        """Retire the MIS Coach group: re-home anyone it was carrying, then
        delete it.

        Two things make this a code migration rather than just dropping the
        record from security/groups.xml:

        * groups.xml is `noupdate="1"`, and ir.model.data._process_end skips
          every noupdate row — so a group declared there is NEVER removed by
          an upgrade, however thoroughly the XML forgets about it.
        * `<menuitem groups="...">` compiles to one Command.link per group,
          so dropping a group from that attribute does not unlink it from
          the menu either. Deleting the group is what clears those seven
          rows, through the m2m foreign key.

        Members first: 18 users held MIS Coach, and for some it was their
        only MIS access. Coaching is no longer a permission, so they are
        given MIS User and keep seeing exactly what they saw — their own
        rows plus their coachees' — now through rule_mis_*_user. Archived
        users are skipped; they cannot log in, and all but two of the 18 are
        archived leftovers of the old auto-sync.

        Runs from data/mis_coach_access_migration.xml, outside noupdate, so
        it also repairs a database upgraded before the group was deleted.
        Idempotent: a no-op once the group is gone.
        """
        coach_grp = self.env.ref('mis_report_kgrn.group_mis_coach',
                                 raise_if_not_found=False)
        if not coach_grp:
            return
        user_grp = self.env.ref('mis_report_kgrn.group_mis_user',
                                raise_if_not_found=False)
        if user_grp:
            # implied_ids means an MIS Manager/Admin is already a member of
            # group_mis_user, so this one check covers the whole role ladder.
            stranded = coach_grp.sudo().users.filtered(
                lambda u: u.active and user_grp not in u.groups_id)
            if stranded:
                user_grp.sudo().write({'users': [(4, u.id) for u in stranded]})
        # Cascades the group off its 18 users and 7 menus, and takes its
        # ir.model.data row with it so the checkbox cannot come back.
        coach_grp.sudo().unlink()
        self.env.registry.clear_cache()

    # ── Give MIS HR the default MIS User dashboard view ───────────────────
    @api.model
    def _mis_grant_hr_dashboard_access(self):
        """Make group_mis_hr imply group_mis_user on an existing database.

        security/groups.xml carries the implication for fresh installs, but
        it is noupdate="1" so `-u` never re-writes an existing group_mis_hr
        record — same reason _mis_migrate_coach_group exists. This forces the
        link; res.groups.write propagates it to every current MIS HR user
        (adding them to group_mis_user) in the same call.

        Effect: MIS HR now also sees Project Wise / Project Revenue /
        Outstandings, scoped to their own projects and coachees by
        rule_mis_*_user exactly as a plain MIS User is — Performance
        Management access is unchanged (group_mis_hr already carried it).

        Runs from data/mis_hr_dashboard_access.xml, outside noupdate, so it
        also repairs a database upgraded before this change. Idempotent: a
        no-op once the implication is in place.
        """
        hr_grp = self.env.ref('mis_report_kgrn.group_mis_hr',
                              raise_if_not_found=False)
        user_grp = self.env.ref('mis_report_kgrn.group_mis_user',
                                raise_if_not_found=False)
        if not hr_grp or not user_grp:
            return
        if user_grp not in hr_grp.implied_ids:
            hr_grp.sudo().write({'implied_ids': [(4, user_grp.id)]})
            self.env.registry.clear_cache()
