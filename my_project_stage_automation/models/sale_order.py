from odoo import models
import logging

logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Called by the base.automation rule when state transitions to 'cancel',
    # and by the daily cron job.
    def _cancel_linked_projects(self):
        for order in self:
            try:
                cancelled_proj_stage = order._get_cancelled_project_stage()

                projects = self.env['project.project'].sudo().with_context(
                    active_test=False
                ).search([('sale_order_id', '=', order.id)])

                if not projects:
                    projects = self.env['project.project'].sudo().with_context(
                        active_test=False
                    ).search([('sale_order_name', '=', order.name)])

                if not projects:
                    logger.info(
                        "[CANCEL] SO '%s' (id=%s): no linked project found.",
                        order.name, order.id,
                    )
                    continue

                for project in projects:
                    cancelled_task_stage = order._get_cancelled_task_stage(project)

                    project.sudo().write({
                        'stage_id': cancelled_proj_stage.id,
                        'active': True,
                    })

                    all_tasks = self.env['project.task'].sudo().with_context(
                        active_test=False
                    ).search([('project_id', '=', project.id)])

                    if all_tasks:
                        all_tasks.sudo().with_context(
                            skip_team_member_notification=True
                        ).write({
                            'stage_id': cancelled_task_stage.id,
                            'state_additional': 'cancelled',
                            'active': True,
                        })

                    logger.info(
                        "[CANCEL] SO '%s' → project '%s': moved to Cancelled, %d task(s).",
                        order.name, project.name, len(all_tasks),
                    )

            except Exception as e:
                logger.exception(
                    "[CANCEL] Error cancelling projects for SO '%s': %s",
                    order.name, e,
                )

    def action_sync_all_cancelled(self):
        """Daily cron: catch any missed cancellations."""
        orders = self.sudo().search([('state', '=', 'cancel')])
        if orders:
            orders._cancel_linked_projects()
            logger.info("[CANCEL SYNC] Processed %d cancelled sale order(s).", len(orders))

    def _get_cancelled_project_stage(self):
        return self._get_or_create_project_stage('Cancelled')

    def _get_cancelled_task_stage(self, project):
        return self._get_or_create_task_stage('Cancelled', project)

    def _get_or_create_project_stage(self, stage_name):
        if stage_name == 'Cancelled':
            try:
                return self.env.ref(
                    'my_project_stage_automation.project_stage_cancelled'
                ).sudo()
            except Exception:
                pass
        stage = self.env['project.project.stage'].sudo().search(
            [('name', '=', stage_name)], limit=1
        )
        if not stage:
            stage = self.env['project.project.stage'].sudo().create(
                {'name': stage_name, 'sequence': 100}
            )
        return stage

    def _get_or_create_task_stage(self, stage_name, project):
        if stage_name == 'Cancelled':
            try:
                stage = self.env.ref(
                    'my_project_stage_automation.task_type_cancelled'
                ).sudo()
                if project and project.id not in stage.project_ids.ids:
                    stage.sudo().write({'project_ids': [(4, project.id)]})
                return stage
            except Exception:
                pass
        stage = self.env['project.task.type'].sudo().search(
            [('name', '=', stage_name)], limit=1
        )
        if not stage:
            stage = self.env['project.task.type'].sudo().create(
                {'name': stage_name, 'sequence': 100}
            )
        if project and project.id not in stage.project_ids.ids:
            stage.sudo().write({'project_ids': [(4, project.id)]})
        return stage
