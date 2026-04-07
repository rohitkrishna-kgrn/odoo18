from odoo import models, fields, api, _
from odoo.exceptions import UserError,AccessError

class TaskExtraHours(models.Model):
    _name = 'task.extra.hours'
    _description = 'Extra Hours Request'
    _order = 'create_date desc'
    _rec_name = 'reason'

    task_id = fields.Many2one('project.task', string="Task", required=True)
    project_id = fields.Many2one('project.project', string="Project", related='task_id.project_id', store=True)
    user_id = fields.Many2one('res.users', string="Requested By", default=lambda self: self.env.user, readonly=True)
    extra_hours = fields.Float(string="Extra Hours", required=True)
    reason = fields.Text(string="Reason", required=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string="Status", default='draft', tracking=True)

    is_approver = fields.Boolean(string="Is Approver", compute='_compute_is_approver')

    @api.depends_context('uid')
    def _compute_is_approver(self):
        is_admin = self.env.user.has_group('base.group_system')
        for rec in self:
            if is_admin:
                rec.is_approver = True
                continue
            employee = self.env['hr.employee'].sudo().search(
                [('user_id', '=', rec.user_id.id)], limit=1)
            manager_user = employee.parent_id.user_id if employee and employee.parent_id else False
            rec.is_approver = bool(manager_user and manager_user.id == self.env.uid)

    def action_open_edit_approve_wizard(self):
        self.ensure_one()
        if not self.is_approver:
            raise AccessError(_("You are not authorized to edit this request."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit & Approve Extra Hours'),
            'res_model': 'approve.extra.hours.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_record_id': self.id,
                'default_extra_hours': self.extra_hours,
            },
        }

    def _check_admin_access(self):
        if not self.env.user.has_group('base.group_system'):
            raise UserError("Only administrators can approve or reject records.")

    def action_approve(self):
        for rec in self:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', rec.user_id.id)], limit=1)
            if not employee:
                raise AccessError(_("No employee record linked to user %s.") % rec.user_id.name)

            manager = employee.parent_id
            manager_user = manager.user_id if manager else False

            # Allow approval by either the employee's manager or an administrator
            is_manager = manager_user.id == self.env.uid if manager_user else False
            is_admin = self.env.user.has_group('base.group_system')

            if not (is_manager or is_admin):
                manager_name = manager.name if manager else "No Manager Assigned"
                raise AccessError(_(
                    "You are not authorized to approve this request.\n"
                    "Only the employee's manager (%s) or an administrator can approve it."
                ) % manager_name)

            # Approve the request using sudo, to bypass write restrictions
            rec.sudo().write({'status': 'approved'})
            if rec.task_id:
                rec.task_id.sudo().write({
                    'allocated_hours': rec.task_id.allocated_hours + rec.extra_hours
                })

            # Send simple approval email
            if rec.user_id and rec.user_id.email:
                template = self.env['mail.mail'].sudo().create({
                    'subject': _('Your Extra Hours Request Has Been Approved'),
                    'body_html': _(
                        '<p>Hello %s,<br/>Your request for extra hours has been approved.</p>'
                    ) % rec.user_id.name,
                    'email_to': rec.user_id.email,
                })
                template.sudo().send()
    

    def action_reject(self):
        for rec in self:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', rec.user_id.id)], limit=1)
            if not employee:
                raise AccessError(_("No employee record linked to user %s.") % rec.user_id.name)

            manager = employee.parent_id
            manager_user = manager.user_id if manager else False

            # Allow rejection by either the employee's manager or an administrator
            is_manager = manager_user.id == self.env.uid if manager_user else False
            is_admin = self.env.user.has_group('base.group_system')

            if not (is_manager or is_admin):
                manager_name = manager.name if manager else "No Manager Assigned"
                raise AccessError(_(
                    "You are not authorized to reject this request.\n"
                    "Only the employee's manager (%s) or an administrator can reject it."
                ) % manager_name)

            # Reject the request using sudo
            rec.sudo().write({'status': 'rejected'})
