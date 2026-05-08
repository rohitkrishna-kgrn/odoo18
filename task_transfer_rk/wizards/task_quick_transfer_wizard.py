from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class TaskQuickTransferWizard(models.TransientModel):
    _name = 'task.quick.transfer.wizard'
    _description = 'Quick Task Transfer from List View'

    task_ids = fields.Many2many(
        'project.task',
        'quick_transfer_task_rel',
        'wizard_id', 'task_id',
        string='Tasks',
    )
    current_assignee_ids = fields.Many2many(
        'res.users',
        'quick_transfer_current_rel',
        'wizard_id', 'user_id',
        string='Current Assignees',
        readonly=True,
    )
    transfer_to_ids = fields.Many2many(
        'res.users',
        'quick_transfer_to_rel',
        'wizard_id', 'user_id',
        string='Transfer To',
        domain="[('share', '=', False)]",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        if active_ids:
            tasks = self.env['project.task'].sudo().browse(active_ids)
            res['task_ids'] = [(6, 0, active_ids)]
            res['current_assignee_ids'] = [(6, 0, tasks.mapped('user_ids').ids)]
        return res

    def action_transfer(self):
        self.ensure_one()
        if not self.task_ids:
            raise ValidationError(_("No tasks selected."))
        if not self.transfer_to_ids:
            raise ValidationError(_("Please select at least one user to transfer to."))

        new_users = self.transfer_to_ids
        transferred_by = self.env.user

        for task in self.task_ids:
            old_assignees = task.sudo().user_ids

            task.with_context(skip_team_member_notification=True).sudo().write({
                'user_ids': [(6, 0, new_users.ids)],
                'team_member_ids': [(6, 0, new_users.ids)],
            })

            self.env['task.transfer'].sudo().create({
                'task_id': task.id,
                'from_user_ids': [(6, 0, old_assignees.ids)],
                'to_user_ids': [(6, 0, new_users.ids)],
                'transferred_by': transferred_by.id,
                'transfer_date': fields.Datetime.now(),
            })

            removed_users = old_assignees - new_users
            for user in removed_users:
                if not (user.partner_id and user.partner_id.email):
                    continue
                self.env['mail.mail'].sudo().create({
                    'subject': _('You Have Been Removed from Task: %s') % task.name,
                    'body_html': self._build_removal_email(user, task, new_users),
                    'email_to': user.partner_id.email,
                    'auto_delete': True,
                }).send()

            added_users = new_users - old_assignees
            for user in added_users:
                if not (user.partner_id and user.partner_id.email):
                    continue
                self.env['mail.mail'].sudo().create({
                    'subject': _('Task Assigned to You: %s') % task.name,
                    'body_html': self._build_assignment_email(user, task, old_assignees),
                    'email_to': user.partner_id.email,
                    'auto_delete': True,
                }).send()

        return {'type': 'ir.actions.act_window_close'}

    def _build_removal_email(self, user, task, new_users):
        to_names = ', '.join(new_users.mapped('name')) if new_users else 'N/A'
        return f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
                <p>Dear <strong>{user.name}</strong>,</p>
                <p>You have been <strong>removed</strong> from the following task:</p>
                <table style="border-collapse: collapse; margin: 12px 0; width: 100%; max-width: 520px;">
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5; width: 40%;">Task</td>
                        <td style="padding: 6px 12px;">{task.name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Project</td>
                        <td style="padding: 6px 12px;">{task.project_id.name or 'N/A'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Reassigned To</td>
                        <td style="padding: 6px 12px;">{to_names}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Transferred By</td>
                        <td style="padding: 6px 12px;">{self.env.user.name}</td>
                    </tr>
                </table>
                <p style="margin-top: 20px;">Best regards,<br/><em>KGRN Chartered Accountants</em></p>
            </div>
        """

    def _build_assignment_email(self, user, task, old_assignees):
        from_names = ', '.join(old_assignees.mapped('name')) if old_assignees else 'N/A'
        return f"""
            <div style="font-family: Arial, sans-serif; font-size: 14px; color: #333;">
                <p>Dear <strong>{user.name}</strong>,</p>
                <p>A task has been <strong>assigned to you</strong>:</p>
                <table style="border-collapse: collapse; margin: 12px 0; width: 100%; max-width: 520px;">
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5; width: 40%;">Task</td>
                        <td style="padding: 6px 12px;">{task.name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Project</td>
                        <td style="padding: 6px 12px;">{task.project_id.name or 'N/A'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Deadline</td>
                        <td style="padding: 6px 12px;">{task.date_deadline or 'Not Set'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Previously Assigned To</td>
                        <td style="padding: 6px 12px;">{from_names}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 12px; font-weight: bold; background: #f5f5f5;">Transferred By</td>
                        <td style="padding: 6px 12px;">{self.env.user.name}</td>
                    </tr>
                </table>
                <p>Please log in to the system to review and begin work on this task.</p>
                <p style="margin-top: 20px;">Best regards,<br/><em>KGRN Chartered Accountants</em></p>
            </div>
        """
