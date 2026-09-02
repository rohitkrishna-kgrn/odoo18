from odoo import models, fields, api, _

from .project_project import DELAY_LOG_STATES


class ProjectTask(models.Model):
    _inherit = 'project.task'

    overdue_days = fields.Integer(
        string='Overdue Days',
        compute='_compute_overdue_category',
    )

    overdue_category = fields.Selection(
        selection=[
            ('none', 'Not Overdue'),
            ('lt30', 'Overdue < 30 days'),
            ('30_60', 'Overdue 30–60 days'),
            ('60_90', 'Overdue 60–90 days'),
            ('gt90', 'Overdue > 90 days'),
            ('done', 'Done'),
        ],
        string='Overdue Category',
        compute='_compute_overdue_category',
    )

    @api.depends('date_deadline', 'stage_id.fold', 'state_additional')
    def _compute_overdue_category(self):
        today = fields.Date.today()   # returns datetime.date, always
        for task in self:
            # Tasks in a folded (done) stage or marked completed carry no overdue status
            is_done = (
                task.state_additional == 'completed'
                or (task.stage_id and task.stage_id.fold)
            )
            if is_done:
                task.overdue_days = 0
                task.overdue_category = 'done'
                continue

            if not task.date_deadline:
                task.overdue_days = 0
                task.overdue_category = 'none'
                continue

            # date_deadline may be a datetime.datetime on some Odoo builds;
            # fields.Date.to_date() normalises both str and datetime → date.
            deadline = fields.Date.to_date(task.date_deadline)
            delta = (today - deadline).days
            task.overdue_days = max(0, delta)

            if delta <= 0:
                task.overdue_category = 'none'
            elif delta < 30:
                task.overdue_category = 'lt30'
            elif delta <= 60:
                task.overdue_category = '30_60'
            elif delta <= 90:
                task.overdue_category = '60_90'
            else:
                task.overdue_category = 'gt90'

    delay_reason = fields.Text(string='Delay Explanation')

    delay_revised_date = fields.Date(string='Revised Delivery Date')

    delay_evidence_ids = fields.Many2many(
        'ir.attachment',
        'project_task_delay_evidence_rel',
        'task_id',
        'attachment_id',
        string='Communication Evidence',
    )

    delay_log_missing = fields.Boolean(
        string='Delay Log Missing',
        compute='_compute_delay_log_missing',
        store=True,
        help="True when the deadline has passed and no delay reason, revised date, "
             "or communication evidence has been logged.",
    )

    delay_log_state = fields.Selection(
        selection=DELAY_LOG_STATES,
        string='Delay Log',
        compute='_compute_delay_log_missing',
        store=True,
        help="Set once the deadline has passed: 'missing' while no delay log has "
             "been recorded, 'logged' afterwards. Empty while the deadline is "
             "still ahead or the task is done.",
    )

    @api.depends(
        'date_deadline', 'stage_id.fold', 'state_additional',
        'delay_reason', 'delay_revised_date', 'delay_evidence_ids',
    )
    def _compute_delay_log_missing(self):
        today = fields.Date.today()
        for task in self:
            is_done = (
                task.state_additional in ('completed', 'cancelled')
                or (task.stage_id and task.stage_id.fold)
            )
            if is_done or not task.date_deadline:
                task.delay_log_missing = False
                task.delay_log_state = False
                continue

            deadline = fields.Date.to_date(task.date_deadline)
            if deadline >= today:
                task.delay_log_missing = False
                task.delay_log_state = False
                continue

            log_populated = bool(
                task.delay_reason or task.delay_revised_date or task.delay_evidence_ids
            )
            task.delay_log_missing = not log_populated
            task.delay_log_state = 'logged' if log_populated else 'missing'

    @api.model
    def _cron_refresh_delay_log_flags(self):
        """date_deadline passing doesn't itself trigger recompute of the stored
        delay_log_missing field, so a daily cron nudges it."""
        tasks = self.search([('date_deadline', '!=', False)])
        tasks._compute_delay_log_missing()

    def action_open_delay_log_wizard(self):
        """Return the delay-log wizard action, or False when nothing is owed.

        Called by the form controller when a task whose deadline has passed is
        opened. The pending state is re-evaluated here against today's date
        rather than trusted from the stored flag, which only refreshes on write
        and on the nightly cron.
        """
        self.ensure_one()
        deadline = fields.Date.to_date(self.date_deadline)
        is_done = (
            self.state_additional in ('completed', 'cancelled')
            or (self.stage_id and self.stage_id.fold)
        )
        log_populated = bool(
            self.delay_reason or self.delay_revised_date or self.delay_evidence_ids
        )
        if is_done or not deadline or deadline >= fields.Date.today() or log_populated:
            return False

        return {
            'type': 'ir.actions.act_window',
            'name': _('Delay Reason'),
            'res_model': 'project.delay.log.wizard',
            'view_mode': 'form',
            # 'views' must be spelled out: the form controller reaches this
            # method through /web/dataset/call_kw, which -- unlike a form
            # button's call_button -- never runs clean_action(), so nothing
            # expands view_mode for the client and action_service crashes on
            # action.views.map().
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_res_model': 'project.task',
                'default_res_id': self.id,
                'default_record_name': self.display_name,
                'default_deadline': fields.Date.to_string(deadline),
            },
        }
