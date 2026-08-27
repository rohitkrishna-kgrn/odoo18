"""Retire the standalone Managing Partner checkbox group.

The credit hold override used to be gated by a bespoke no-category group,
`account_extended_rk.group_credit_hold_managing_partner`. Nobody was ever
ticked into it, so the override button was invisible to every user. At the
firm's instruction the authority now rides on the standard Accounting
'Advisor' level (`account.group_account_manager`) instead, which already has
the right people in it and is set from the familiar Accounting dropdown.

Deleting the group is safe: its only ACL row was repointed in the same
release, and no record rule or view still references it. Odoo's own orphan
sweep normally removes it, but it is done explicitly here so the upgrade is
not silently dependent on that.
"""
import logging

_logger = logging.getLogger(__name__)

XMLID = 'account_extended_rk.group_credit_hold_managing_partner'


def migrate(cr, version):
    if not version:
        return

    cr.execute(
        """
        SELECT res_id FROM ir_model_data
         WHERE module = 'account_extended_rk'
           AND name = 'group_credit_hold_managing_partner'
           AND model = 'res.groups'
        """
    )
    row = cr.fetchone()
    if not row:
        _logger.info("%s already gone, nothing to retire.", XMLID)
        return

    gid = row[0]

    # Anyone ticked into the old group keeps working only if they also hold
    # Advisor. Report the gap rather than silently granting it.
    cr.execute("SELECT uid FROM res_groups_users_rel WHERE gid = %s", (gid,))
    old_members = [r[0] for r in cr.fetchall()]
    if old_members:
        cr.execute(
            """
            SELECT u.uid FROM res_groups_users_rel u
             WHERE u.uid = ANY(%s)
               AND u.gid = (SELECT res_id FROM ir_model_data
                             WHERE module = 'account' AND name = 'group_account_manager'
                               AND model = 'res.groups')
            """,
            (old_members,),
        )
        covered = {r[0] for r in cr.fetchall()}
        orphaned = sorted(set(old_members) - covered)
        if orphaned:
            _logger.warning(
                "Users %s held the retired credit hold override group but are "
                "not Accounting Advisors; they lose override rights. Set "
                "Accounting = Advisor on those users if that is wrong.",
                orphaned,
            )

    cr.execute("DELETE FROM res_groups_users_rel WHERE gid = %s", (gid,))
    cr.execute("DELETE FROM ir_model_access WHERE group_id = %s", (gid,))
    cr.execute("DELETE FROM rule_group_rel WHERE group_id = %s", (gid,))
    cr.execute("DELETE FROM res_groups WHERE id = %s", (gid,))
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'account_extended_rk'
           AND name = 'group_credit_hold_managing_partner'
        """
    )
    _logger.info("Retired %s (group id %s); override now gated by Advisor.", XMLID, gid)
