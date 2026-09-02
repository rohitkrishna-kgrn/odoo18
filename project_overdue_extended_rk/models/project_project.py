from odoo import models, fields, api, _

# Shared by project.project and project.task (imported by project_task.py) so
# the two list badges always read with the same wording.
DELAY_LOG_STATES = [
    ('missing', 'Deadline passed but no log'),
    ('logged', 'Deadline passed logs available'),
]


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # The project deadline is the core planned end date ('date', shown as
    # Deadline on the form): it is what the SO line's engagement end writes to,
    # what the MIS report reads, and what the deadline alerts fire on.

    delay_reason = fields.Text(string='Delay Explanation')

    delay_revised_date = fields.Date(string='Revised Delivery Date')

    delay_evidence_ids = fields.Many2many(
        'ir.attachment',
        'project_project_delay_evidence_rel',
        'project_id',
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
             "still ahead or the project is done.",
    )

    @api.depends(
        'date', 'stage_id.fold',
        'delay_reason', 'delay_revised_date', 'delay_evidence_ids',
    )
    def _compute_delay_log_missing(self):
        today = fields.Date.today()
        for project in self:
            is_done = bool(project.stage_id and project.stage_id.fold)
            if is_done or not project.date:
                project.delay_log_missing = False
                project.delay_log_state = False
                continue

            deadline = fields.Date.to_date(project.date)
            if deadline >= today:
                project.delay_log_missing = False
                project.delay_log_state = False
                continue

            log_populated = bool(
                project.delay_reason or project.delay_revised_date or project.delay_evidence_ids
            )
            project.delay_log_missing = not log_populated
            project.delay_log_state = 'logged' if log_populated else 'missing'

    @api.model
    def _cron_refresh_delay_log_flags(self):
        """the deadline passing doesn't itself trigger recompute of the stored
        delay_log_missing field, so a daily cron nudges it."""
        projects = self.search([('date', '!=', False)])
        projects._compute_delay_log_missing()

    def action_open_delay_log_wizard(self):
        """Return the delay-log wizard action, or False when nothing is owed.

        Called by the form controller when a project whose deadline has passed
        is opened. The pending state is re-evaluated here against today's date
        rather than trusted from the stored flag, which only refreshes on write
        and on the nightly cron.
        """
        self.ensure_one()
        deadline = fields.Date.to_date(self.date)
        is_done = bool(self.stage_id and self.stage_id.fold)
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
                'default_res_model': 'project.project',
                'default_res_id': self.id,
                'default_record_name': self.display_name,
                'default_deadline': fields.Date.to_string(deadline),
            },
        }
