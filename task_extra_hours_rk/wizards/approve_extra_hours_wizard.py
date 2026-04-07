from odoo import models, fields, api, _
from odoo.exceptions import AccessError


class ApproveExtraHoursWizard(models.TransientModel):
    _name = 'approve.extra.hours.wizard'
    _description = 'Approve Extra Hours Wizard'

    record_id = fields.Many2one('task.extra.hours', string="Request", required=True)
    task_id = fields.Many2one(related='record_id.task_id', string="Task", readonly=True)
    user_id = fields.Many2one(related='record_id.user_id', string="Requested By", readonly=True)
    reason = fields.Text(related='record_id.reason', string="Reason", readonly=True)
    extra_hours = fields.Float(string="Extra Hours", required=True)

    def action_approve(self):
        self.ensure_one()
        record = self.record_id
        if not record.is_approver:
            raise AccessError(_("You are not authorized to approve this request."))
        record.sudo().write({'extra_hours': self.extra_hours})
        record.action_approve()

    def action_reject(self):
        self.ensure_one()
        record = self.record_id
        if not record.is_approver:
            raise AccessError(_("You are not authorized to reject this request."))
        record.action_reject()
