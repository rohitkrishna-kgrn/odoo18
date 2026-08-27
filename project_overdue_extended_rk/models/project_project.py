from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

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

    @api.depends(
        'deadline', 'stage_id.fold',
        'delay_reason', 'delay_revised_date', 'delay_evidence_ids',
    )
    def _compute_delay_log_missing(self):
        today = fields.Date.today()
        for project in self:
            is_done = bool(project.stage_id and project.stage_id.fold)
            if is_done or not project.deadline:
                project.delay_log_missing = False
                continue

            deadline = fields.Date.to_date(project.deadline)
            log_populated = bool(
                project.delay_reason or project.delay_revised_date or project.delay_evidence_ids
            )
            project.delay_log_missing = deadline < today and not log_populated

    @api.model
    def _cron_refresh_delay_log_flags(self):
        """deadline passing doesn't itself trigger recompute of the stored
        delay_log_missing field, so a daily cron nudges it."""
        projects = self.search([('deadline', '!=', False)])
        projects._compute_delay_log_missing()
