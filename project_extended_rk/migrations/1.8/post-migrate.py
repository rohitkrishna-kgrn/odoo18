import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Seed the hold-stage flag, then backfill the 'On Hold' task tag.

    Two things the module data files cannot do on their own:

    1. Which project stage means "on hold" is data, not code - this DB renamed
       the core stage records, so the automation keys off a boolean on
       project.project.stage rather than an XML id. Seed it from stage names.

    2. Projects already sitting on hold at upgrade time never fire the write()
       hook, so their open tasks would stay untagged until someone re-saved the
       project. Tag them once, here.
    """
    cr.execute("""
        UPDATE project_project_stage
           SET is_hold_stage = TRUE
         WHERE lower(name->>'en_US') LIKE '%%hold%%'
           AND COALESCE(is_hold_stage, FALSE) = FALSE
    """)
    _logger.info(
        "project_extended_rk: flagged %s project stage(s) as hold stages",
        cr.rowcount,
    )

    env = api.Environment(cr, SUPERUSER_ID, {})

    # is_on_hold was computed during module load, before the raw SQL above.
    # Force it to be recomputed now that the stages carry the flag.
    env['project.project.stage'].invalidate_model(['is_hold_stage'])
    all_projects = env['project.project'].with_context(active_test=False).search([])
    all_projects.invalidate_recordset(['is_on_hold'])
    all_projects.modified(['stage_id', 'last_update_status'])
    env.flush_all()

    held = env['project.project'].search([('is_on_hold', '=', True)])
    if not held:
        _logger.info("project_extended_rk: no project on hold, nothing to backfill")
        return

    before = env['project.task'].search_count([('is_on_hold', '=', True)])
    held._sync_task_hold_tag()
    env.flush_all()
    after = env['project.task'].search_count([('is_on_hold', '=', True)])

    _logger.info(
        "project_extended_rk: On Hold backfill - %s project(s) on hold, "
        "%s task(s) newly tagged 'On Hold' (%s -> %s)",
        len(held), after - before, before, after,
    )
