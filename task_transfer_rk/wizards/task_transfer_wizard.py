from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class TaskTransferWizard(models.TransientModel):
    _name = 'task.transfer.wizard'
    _description = 'Task Transfer Wizard'

    project_id = fields.Many2one('project.project', string='Project', required=True)
    task_ids = fields.Many2many(
        'project.task',
        'wizard_transfer_task_rel',
        'wizard_id', 'task_id',
        string='Tasks',
        required=True,
    )
    current_assignee_ids = fields.Many2many(
        'res.users',
        string='Current Assignees',
        compute='_compute_current_assignees',
        readonly=True,
    )
    employee_user_ids = fields.Many2many(
        'res.users',
        string='Employee Users',
        compute='_compute_employee_user_ids',
    )
    add_assignee_ids = fields.Many2many(
        'res.users',
        'wizard_transfer_add_rel',
        'wizard_id', 'user_id',
        string='Transfer Assignees',
    )
    team_member_ids = fields.Many2many(
        'res.users',
        'wizard_transfer_team_rel',
        'wizard_id', 'user_id',
        string='Add or Remove Team Members',
    )

    @api.depends('task_ids')
    def _compute_current_assignees(self):
        for rec in self:
            rec.current_assignee_ids = rec.task_ids.sudo().mapped('user_ids')

    @api.depends('task_ids')
    def _compute_employee_user_ids(self):
        emp_users = self.env['hr.employee'].sudo().search(
            [('user_id', '!=', False)]
        ).mapped('user_id')
        for rec in self:
            rec.employee_user_ids = emp_users

    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.task_ids = False
        self.add_assignee_ids = False
        self.team_member_ids = False

    @api.onchange('task_ids')
    def _onchange_task_ids(self):
        self.add_assignee_ids = False
        self.team_member_ids = False

    def action_transfer(self):
        self.ensure_one()
        if not self.env.user.has_group('task_transfer_rk.group_task_transfer_user'):
            raise UserError(_("You do not have the access rights to transfer tasks."))
        if not self.task_ids:
            raise ValidationError(_("Please select at least one task to transfer."))
        if not self.add_assignee_ids:
            raise ValidationError(_("Please select at least one assignee to transfer to."))

        new_members = self.add_assignee_ids
        transferred_by = self.env.user

        for task in self.task_ids:
            old_members = task.sudo().user_ids
            write_vals = {'user_ids': [(6, 0, new_members.ids)]}
            if self.team_member_ids:
                write_vals['team_member_ids'] = [(6, 0, self.team_member_ids.ids)]
            task.with_context(skip_team_member_notification=True).sudo().write(write_vals)

            removed_users = old_members - new_members
            added_users = new_members - old_members

            self.env['task.transfer'].sudo().create({
                'task_id': task.id,
                'from_user_ids': [(6, 0, old_members.ids)],
                'to_user_ids': [(6, 0, new_members.ids)],
                'transferred_by': transferred_by.id,
                'transfer_date': fields.Datetime.now(),
            })

            for user in removed_users:
                if not (user.partner_id and user.partner_id.email):
                    continue
                self.env['mail.mail'].sudo().create({
                    'subject': _('You Have Been Removed from Task: %s') % task.name,
                    'body_html': self._build_removal_email(user, task, new_members),
                    'email_to': user.partner_id.email,
                    'auto_delete': True,
                }).send()

            for user in added_users:
                if not (user.partner_id and user.partner_id.email):
                    continue
                self.env['mail.mail'].sudo().create({
                    'subject': _('Task Assigned to You: %s') % task.name,
                    'body_html': self._build_assignment_email(user, task, old_members),
                    'email_to': user.partner_id.email,
                    'auto_delete': True,
                }).send()

        return {'type': 'ir.actions.act_window_close'}

    def _build_removal_email(self, user, task, new_members):
        to_names = ', '.join(new_members.mapped('name')) if new_members else 'N/A'
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

    def _build_assignment_email(self, user, task, old_members):
        from_names = ', '.join(old_members.mapped('name')) if old_members else 'N/A'
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
