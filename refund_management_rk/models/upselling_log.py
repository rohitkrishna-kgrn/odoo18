from odoo import models, fields, api, _

# Every workflow action that must appear in the Upselling "Log" tab.
UPSELLING_LOG_ACTIONS = [
    ('submit_review', 'Submit for Review'),
    ('submit_approval', 'Submit for Approval'),
    ('reset_review', 'Reset to Review'),
    ('resubmit_approval', 'Re-Submit for Approval'),
    ('reject', 'Reject Upselling'),
    ('approve', 'Approve'),
]


class UpsellingLog(models.Model):
    _name = 'upselling.log'
    _description = 'Upselling Action Log'
    # Chronological: oldest action first, so the tab reads like a history.
    _order = 'log_date asc, id asc'

    upselling_id = fields.Many2one(
        'upselling', string='Upselling', required=True,
        ondelete='cascade', index=True
    )
    log_date = fields.Datetime(
        string='Date/Time', required=True, default=fields.Datetime.now
    )
    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        default=lambda self: self.env.user
    )
    action = fields.Selection(UPSELLING_LOG_ACTIONS, string='Action', required=True)
    reason = fields.Text(string='Reason/Remark')
    # Actions that need no reason still get a row, shown as N/A rather than blank.
    reason_display = fields.Char(
        string='Reason/Remark', compute='_compute_reason_display'
    )

    @api.depends('reason')
    def _compute_reason_display(self):
        for log in self:
            log.reason_display = (log.reason or '').strip() or _('N/A')

    def action_label(self):
        """Translated label of the logged action, for chatter messages."""
        self.ensure_one()
        selection = dict(self._fields['action']._description_selection(self.env))
        return selection.get(self.action, self.action)
