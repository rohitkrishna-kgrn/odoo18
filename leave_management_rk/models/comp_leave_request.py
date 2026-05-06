from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import date


class LeaveCompRequest(models.Model):
    _name = 'leave.comp.request'
    _description = 'Compensation Leave Request'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='Employee', default=lambda self: self.env.user, required=True)
    attendance_id = fields.Many2one('hr.attendance', string='Date Worked', ondelete='set null')
    date_worked = fields.Date(string='Date Worked', compute='_compute_date_worked', store=True)
    days = fields.Float(string='Days to Compensate', default=1.0, required=True)
    reason = fields.Text(string='Reason / Description')
    manager_remarks = fields.Text(string='Manager Remarks')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_manager', 'Waiting Manager Approval'),
        ('manager_approved', 'Manager Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status')

    eligible_attendance_ids = fields.Many2many(
        'hr.attendance',
        string='Eligible Dates (Sundays & Public Holidays)',
        compute='_compute_eligible_attendance',
        store=False
    )

    @api.depends('attendance_id')
    def _compute_date_worked(self):
        for rec in self:
            if rec.attendance_id and rec.attendance_id.check_in:
                rec.date_worked = rec.attendance_id.check_in.date()
            else:
                rec.date_worked = False

    @api.depends('user_id')
    def _compute_eligible_attendance(self):
        PublicHoliday = self.env['public.holiday']
        HrAttendance = self.env['hr.attendance']

        for rec in self:
            if not rec.user_id:
                rec.eligible_attendance_ids = HrAttendance
                continue

            employee = self.env['hr.employee'].search(
                [('user_id', '=', rec.user_id.id)], limit=1
            )
            if not employee:
                rec.eligible_attendance_ids = HrAttendance
                continue

            holiday_dates = {ph.date for ph in PublicHoliday.search([])}

            attendances = HrAttendance.search([
                ('employee_id', '=', employee.id),
            ], order='check_in desc', limit=500)

            eligible = HrAttendance
            seen_dates = set()
            for att in attendances:
                if not att.check_in:
                    continue
                att_date = att.check_in.date()
                if att_date in seen_dates:
                    continue
                if att_date.weekday() == 6 or att_date in holiday_dates:
                    eligible |= att
                    seen_dates.add(att_date)

            rec.eligible_attendance_ids = eligible

    def _get_employee_manager_user(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.user_id.id)], limit=1
        )
        if employee and employee.parent_id and employee.parent_id.user_id:
            return employee.parent_id.user_id
        return False

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError("Only draft requests can be submitted.")
            if not rec.attendance_id:
                raise UserError("Please select a worked day from the eligible attendance list.")
            if rec.days <= 0:
                raise UserError("Days must be greater than 0.")

            manager_user = rec._get_employee_manager_user()
            if manager_user:
                rec.write({'state': 'waiting_manager'})
                rec._send_mail_to_manager(manager_user)
            else:
                rec.write({'state': 'manager_approved'})
                rec._send_mail_to_hr()

    def action_manager_approve(self):
        for rec in self:
            if rec.state != 'waiting_manager':
                raise UserError("Only requests waiting for manager approval can be approved here.")
            rec.write({'state': 'manager_approved'})
            rec._send_mail_to_hr()

    def action_manager_reject_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject with Remarks',
            'res_model': 'leave.manager.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_comp_leave_id': self.id},
        }

    def action_approve(self):
        for rec in self:
            if rec.state != 'manager_approved':
                raise UserError("Only manager-approved requests can be approved by HR.")
            LeaveType = self.env['leave.type']
            LeaveBalance = self.env['leave.balance']
            comp_leave = LeaveType.search([('name', '=', 'Compensation Leave')], limit=1)
            if not comp_leave:
                raise UserError("Compensation Leave type not found.")
            today = date.today()
            first_of_month = today.replace(day=1)
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', comp_leave.id),
                ('date', '=', first_of_month)
            ], limit=1)
            if balance_record:
                balance_record.balance += rec.days
            else:
                LeaveBalance.create({
                    'user_id': rec.user_id.id,
                    'leave_type_id': comp_leave.id,
                    'date': first_of_month,
                    'balance': rec.days,
                })
            rec.write({'state': 'approved'})

    def action_reject(self):
        for rec in self:
            if rec.state in ('approved', 'rejected'):
                raise UserError("Cannot reject an already approved or rejected request.")
            rec.write({'state': 'rejected'})

    def _send_mail_to_manager(self, manager_user):
        if not manager_user.email:
            return
        body_html = f"""
            <p>Dear {manager_user.name},</p>
            <p><strong>{self.user_id.name}</strong> has submitted a Compensation Leave request requiring your approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Date Worked</b></td><td style="padding:4px 10px;">{self.date_worked}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Days</b></td><td style="padding:4px 10px;">{self.days}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Reason</b></td><td style="padding:4px 10px;">{self.reason or '-'}</td></tr>
            </table>
            <p>Please go to <b>Leave → Team Approval → Compensation</b> to review.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Compensation Leave Approval Needed — {self.user_id.name}",
            'body_html': body_html,
            'email_to': manager_user.email,
            'auto_delete': True,
        }).send()

    def _send_mail_to_hr(self):
        hr_group = self.env.ref('leave_management_rk.group_hr_manager', raise_if_not_found=False)
        if not hr_group:
            return
        hr_emails = [u.email for u in hr_group.users if u.email]
        if not hr_emails:
            return
        body_html = f"""
            <p>Dear HR,</p>
            <p>A Compensation Leave request from <strong>{self.user_id.name}</strong> has been approved by the department manager and awaits your final approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Date Worked</b></td><td style="padding:4px 10px;">{self.date_worked}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Days</b></td><td style="padding:4px 10px;">{self.days}</td></tr>
            </table>
            <p>Please go to <b>Leave → Team Approval → Compensation</b> to proceed.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Compensation Leave Ready for HR Approval — {self.user_id.name}",
            'body_html': body_html,
            'email_to': ','.join(hr_emails),
            'auto_delete': True,
        }).send()
