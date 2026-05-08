from . import models
import logging

logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Runs on install and upgrade — syncs all cancelled SOs to Cancelled stage."""
    _sync_cancelled_orders(env)


def _sync_cancelled_orders(env):
    logger.info("[SYNC] Looking for cancelled sale orders to sync...")
    orders = env['sale.order'].sudo().search([('state', '=', 'cancel')])
    logger.info("[SYNC] Found %d cancelled sale order(s).", len(orders))
    if not orders:
        return

    cancelled_proj_stage = _get_or_create_project_stage(env)
    cancelled_task_stage_global = _get_or_create_task_stage_global(env)

    synced_projects = 0
    synced_tasks = 0

    for order in orders:
        projects = env['project.project'].sudo().with_context(active_test=False).search(
            [('sale_order_id', '=', order.id)]
        )
        if not projects:
            projects = env['project.project'].sudo().with_context(active_test=False).search(
                [('sale_order_name', '=', order.name)]
            )
        if not projects:
            logger.info("[SYNC] SO '%s': no linked project.", order.name)
            continue

        for project in projects:
            # Link the global Cancelled task stage to this project
            if project.id not in cancelled_task_stage_global.project_ids.ids:
                cancelled_task_stage_global.sudo().write({'project_ids': [(4, project.id)]})

            project.sudo().write({'stage_id': cancelled_proj_stage.id, 'active': True})
            synced_projects += 1

            tasks = env['project.task'].sudo().with_context(active_test=False).search(
                [('project_id', '=', project.id)]
            )
            if tasks:
                tasks.sudo().with_context(skip_team_member_notification=True).write({
                    'stage_id': cancelled_task_stage_global.id,
                    'state_additional': 'cancelled',
                    'active': True,
                })
                synced_tasks += len(tasks)

            logger.info("[SYNC] SO '%s' → project '%s': cancelled.", order.name, project.name)

    logger.info(
        "[SYNC] Done — %d project(s) and %d task(s) moved to Cancelled.",
        synced_projects, synced_tasks,
    )


def _get_or_create_project_stage(env):
    try:
        return env.ref('my_project_stage_automation.project_stage_cancelled').sudo()
    except Exception:
        pass
    stage = env['project.project.stage'].sudo().search([('name', '=', 'Cancelled')], limit=1)
    if not stage:
        stage = env['project.project.stage'].sudo().create(
            {'name': 'Cancelled', 'sequence': 100}
        )
    return stage


def _get_or_create_task_stage_global(env):
    try:
        return env.ref('my_project_stage_automation.task_type_cancelled').sudo()
    except Exception:
        pass
    stage = env['project.task.type'].sudo().search([('name', '=', 'Cancelled')], limit=1)
    if not stage:
        stage = env['project.task.type'].sudo().create(
            {'name': 'Cancelled', 'sequence': 100}
        )
    return stage
