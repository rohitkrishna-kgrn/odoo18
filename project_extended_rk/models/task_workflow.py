from odoo import models, fields, _
from odoo.exceptions import UserError
import logging

logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    """The task workflow buttons: New/On Hold -> In Progress -> Waiting For
    Approval -> Completed, with On Hold and Retrieve as the way back.

    These lived in `my_project_stage_automation`, which was uninstalled on
    2026-08-14 and took the header buttons with it -- the `state_additional`
    badge and its filters stayed behind here, so tasks showed a state nobody
    could move. The buttons are restored in this module, which already owns
    `state_additional`, `completed_date` and the hold machinery they drive.

    Deliberately NOT brought back with them: that module's firm-wide
    auto-cancel automation, its post-install hook, and the auto-invoice on
    approval (`project_closure_invoice_gate_rk` owns closure invoicing now).
    """
    _inherit = 'project.task'

    # ------------------------------------------------------------------
    # Stage resolution
    # ------------------------------------------------------------------
    def _workflow_task_stage(self, name):
        """The named task stage, linked to this task's project.

        Task stages are per-project in Odoo: a stage the project does not
        carry is invisible in the statusbar and the kanban column, so the
        project is added to the stage the first time it is needed -- the same
        thing `_hold_task_stage` does for the hold stage. A stage the project
        already carries wins over the global one, because most projects here
        hold their own copy of the standard stages (there are 100+ rows named
        'Done' in this database). The match is case-insensitive: the live data
        has both 'In Progress' and 'In progress'.
        """
        self.ensure_one()
        Stage = self.env['project.task.type'].sudo()
        domain = [('name', '=ilike', name)]
        stage = Stage.browse()
        if self.project_id:
            stage = Stage.search(
                domain + [('project_ids', 'in', self.project_id.id)],
                order='sequence, id', limit=1)
        if not stage:
            stage = Stage.search(domain, order='sequence, id', limit=1)
        if not stage:
            raise UserError(_(
                "The '%s' task stage does not exist. Create it under "
                "Project > Configuration > Task Stages before using this "
                "button.", name))
        if self.project_id and self.project_id not in stage.project_ids:
            stage.write({'project_ids': [(4, self.project_id.id)]})
        return stage

    def _workflow_project_stage(self, name):
        """The named project stage, or a clear error naming what is missing."""
        stage = self.env['project.project.stage'].sudo().search(
            [('name', '=ilike', name)], order='sequence, id', limit=1)
        if not stage:
            raise UserError(_(
                "The '%s' project stage does not exist. Create it under "
                "Project > Configuration > Project Stages before using this "
                "button.", name))
        return stage

    def _set_sale_order_status(self, status):
        """Mirror the task's progress onto the sale order behind the project.

        The link is the order *name* carried on the project, not a relation --
        that is how this codebase has always joined the two.
        """
        self.ensure_one()
        order_name = self.project_id.sale_order_name if self.project_id else False
        if not order_name:
            return
        order = self.env['sale.order'].sudo().search(
            [('name', '=', order_name)], limit=1)
        if not order:
            logger.warning("[TASK] No sale order found named '%s'", order_name)
            return
        if order.order_status != status:
            order.write({'order_status': status})

    # ------------------------------------------------------------------
    # Workflow buttons
    # ------------------------------------------------------------------
    def action_in_progress(self):
        """Start the task -- also the way back off a hold."""
        self.ensure_one()
        if not self.team_member_ids:
            raise UserError(_(
                "Cannot set task to 'In Progress' without assigned team "
                "members."))

        vals = {
            'stage_id': self._workflow_task_stage('In Progress').id,
            'state_additional': 'in_progress',
        }
        # Coming off a hold, the remembered stage is no longer owed to anyone.
        if self.state_additional == 'on_hold':
            vals.update(hold_auto=False, hold_prev_stage_id=False,
                        hold_prev_state_additional=False)
        self.write(vals)

        if self.project_id:
            self.project_id.write(
                {'stage_id': self._workflow_project_stage('In Progress').id})

        self._set_sale_order_status('opened')
        return True

    def action_on_hold(self):
        """Park an in-progress task.

        Held by hand, so `hold_auto` stays False: the project-hold cascade in
        project.py only releases what it parked itself, and a hold somebody
        asked for should outlive the project coming off hold.
        """
        self.ensure_one()
        if self.state_additional != 'in_progress':
            raise UserError(_("Only an 'In Progress' task can be put On Hold."))

        hold_stage = self._hold_task_stage(self.project_id)
        if not hold_stage:
            raise UserError(_(
                "The 'On Hold' task stage is missing. It ships with this "
                "module as project_extended_rk.project_task_type_on_hold."))
        self.write({
            'stage_id': hold_stage.id,
            'state_additional': 'on_hold',
            'hold_prev_stage_id': self.stage_id.id,
            'hold_prev_state_additional': self.state_additional,
        })

        # One task on hold puts the whole project on hold, as before.
        if self.project_id:
            self.project_id.write(
                {'stage_id': self._workflow_project_stage('On Hold').id})
        return True

    def action_send_for_approval(self):
        self.ensure_one()
        if self.state_additional == 'waiting_for_approval':
            raise UserError(_("The task is already Waiting For Approval."))
        if self.state_additional != 'in_progress':
            raise UserError(_(
                "Only an 'In Progress' task can be sent for approval."))
        self.write({
            'stage_id': self._workflow_task_stage('Waiting For Approval').id,
            'state_additional': 'waiting_for_approval',
        })
        return True

    def action_approve(self):
        self.ensure_one()
        if self.state_additional == 'completed':
            raise UserError(_("The task is already completed."))

        project = self.project_id
        if not project:
            raise UserError(_("The task is not associated with any project."))
        if self.env.user not in project.user_id:
            raise UserError(_("Only project managers can approve tasks."))

        self.write({
            'stage_id': self._workflow_task_stage('Done').id,
            'state_additional': 'completed',
            'completed_date': fields.Datetime.now(),
            'hold_auto': False,
            'hold_prev_stage_id': False,
            'hold_prev_state_additional': False,
        })

        if self.sale_line_id:
            self.sale_line_id.sudo().write(
                {'qty_delivered': self.sale_line_id.qty_delivered + 1})

        # The engagement closes only once every one of its tasks is finished.
        if all(task._is_task_closed() for task in project.task_ids):
            project.sudo().write({
                'stage_id': self._workflow_project_stage('Done').id,
                'completed_date': fields.Datetime.now(),
            })
            self._notify_project_completed(project)
            self._set_sale_order_status('closed')
        return True

    def action_retrieve(self):
        """Pull a task back out of approval."""
        self.ensure_one()
        self.write({
            'stage_id': self._workflow_task_stage('In Progress').id,
            'state_additional': 'in_progress',
        })
        return True

    def _notify_project_completed(self, project):
        approver = self.env.company.approver_user_id
        if not (approver and approver.email):
            return
        self.env['mail.mail'].sudo().create({
            'subject': _("Project '%s' Completed", project.name),
            'body_html': _(
                "<p>Dear %(approver)s,</p>"
                "<p>Project <strong>%(project)s</strong> has been marked as "
                "<span style=\"color:green;\">Done</span>.</p>"
                "<p>Completion Date: %(date)s</p>"
                "<p><em>KGRN Chartered Accountants</em></p>",
                approver=approver.name,
                project=project.name,
                date=fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ),
            'email_to': approver.email,
        }).send()
