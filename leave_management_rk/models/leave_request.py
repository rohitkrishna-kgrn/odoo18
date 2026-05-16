from odoo import models, fields, api
from odoo.exceptions import UserError

HALF_DAY_TYPES = ['Sick Leave', 'Casual Leave']


class LeaveRequest(models.Model):
    _name = 'leave.request'
    _description = 'Leave Request'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user, required=True)
    leave_type_id = fields.Many2one('leave.type', string='Leave Type', required=True)
    is_half_day = fields.Boolean(string='Half Day')
    start_date = fields.Date(string='Start Date / Date', required=True)
    end_date = fields.Date(string='End Date')
    days_requested = fields.Float(string='Days Requested', compute='_compute_days_requested', store=True)
    hours_requested = fields.Float(string='Hours Requested')
    reason = fields.Text(string='Reason')
    applied_date = fields.Datetime(string='Applied Date', readonly=True)
    dha_certificate = fields.Binary(string='Upload DHA Sick Leave Certificate')
    dha_certificate_filename = fields.Char(string='DHA Certificate Filename')
    is_dubai_sick_leave = fields.Boolean(
        compute='_compute_is_dubai_sick_leave', store=False
    )
    manager_remarks = fields.Text(string='Manager Remarks')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_manager', 'Waiting Manager Approval'),
        ('manager_approved', 'Manager Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status')
    paid = fields.Boolean(string='Paid Leave')
    balance_deducted = fields.Boolean(string='Balance Deducted', default=False)
    available_balance = fields.Float(
        string="Available Balance (Days / Hrs)",
        compute='_compute_available_balance',
        store=False
    )
    is_permission_type = fields.Boolean(
        string='Is Permission',
        compute='_compute_is_permission_type',
        store=False
    )

    @api.depends('user_id', 'leave_type_id', 'days_requested')
    def _compute_is_dubai_sick_leave(self):
        for rec in self:
            rec.is_dubai_sick_leave = (
                rec.user_id.country == 'dubai'
                and rec.leave_type_id
                and rec.leave_type_id.name == 'Sick Leave'
                and rec.days_requested >= 2
            )

    @api.depends('leave_type_id')
    def _compute_is_permission_type(self):
        for rec in self:
            rec.is_permission_type = bool(rec.leave_type_id and rec.leave_type_id.is_permission)

    @api.depends('user_id', 'leave_type_id', 'start_date')
    def _compute_available_balance(self):
        LeaveBalance = self.env['leave.balance']
        today = fields.Date.today()
        for rec in self:
            rec.available_balance = 0.0
            if not rec.user_id or not rec.leave_type_id:
                continue
            ref_date = rec.start_date or today
            first_of_month = ref_date.replace(day=1)
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('date', '=', first_of_month),
            ], limit=1)
            rec.available_balance = balance_record.balance if balance_record else 0.0

    @api.depends('start_date', 'end_date', 'is_half_day', 'leave_type_id')
    def _compute_days_requested(self):
        for rec in self:
            if rec.leave_type_id and rec.leave_type_id.is_permission:
                rec.days_requested = 0.0
            elif rec.is_half_day:
                rec.days_requested = 0.5
            elif rec.start_date and rec.end_date:
                rec.days_requested = float((rec.end_date - rec.start_date).days + 1)
            else:
                rec.days_requested = 0.0

    @api.onchange('is_half_day', 'start_date')
    def _onchange_half_day(self):
        if self.is_half_day and self.start_date:
            self.end_date = self.start_date

    @api.onchange('leave_type_id')
    def _onchange_leave_type(self):
        if self.leave_type_id and not self.leave_type_id.is_permission:
            self.hours_requested = 0.0
        if self.leave_type_id and self.leave_type_id.name not in HALF_DAY_TYPES:
            self.is_half_day = False
        if self.leave_type_id and self.leave_type_id.is_permission:
            self.is_half_day = False

    def _get_employee_manager_user(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.user_id.id)], limit=1
        )
        if employee and employee.parent_id and employee.parent_id.user_id:
            return employee.parent_id.user_id
        return False

    def action_request(self):
        for rec in self:
            if not rec.leave_type_id:
                raise UserError("Please select a Leave Type.")

            LeaveBalance = self.env['leave.balance']
            first_of_month = (rec.start_date or fields.Date.today()).replace(day=1)
            balance_record = LeaveBalance.search([
                ('user_id', '=', rec.user_id.id),
                ('leave_type_id', '=', rec.leave_type_id.id),
                ('date', '=', first_of_month)
            ], limit=1)
            current_balance = balance_record.balance if balance_record else 0

            if rec.leave_type_id.is_permission:
                if not rec.hours_requested or rec.hours_requested <= 0:
                    raise UserError("Please specify hours requested for permission leave.")
                if rec.hours_requested > current_balance:
                    raise UserError(
                        f"Insufficient permission hours. Available: {current_balance} hrs, "
                        f"Requested: {rec.hours_requested} hrs"
                    )
            else:
                if not rec.end_date:
                    raise UserError("Please specify an end date.")
                if rec.is_half_day and rec.leave_type_id.name not in HALF_DAY_TYPES:
                    raise UserError("Half day is only applicable for Sick Leave and Casual Leave.")
                if rec.days_requested > current_balance:
                    raise UserError(
                        f"Insufficient leave balance for {rec.leave_type_id.name}. "
                        f"Available: {current_balance}, Requested: {rec.days_requested}"
                    )

            if rec.is_dubai_sick_leave and not rec.dha_certificate:
                raise UserError(
                    "A DHA Sick Leave Certificate is mandatory for Dubai employees "
                    "requesting Sick Leave of 2 or more days."
                )

            manager_user = rec._get_employee_manager_user()
            if manager_user:
                rec.write({'state': 'waiting_manager', 'applied_date': fields.Datetime.now()})
                rec._send_mail_to_manager(manager_user)
            else:
                # No manager configured — skip to manager_approved, notify HR
                rec.write({'state': 'manager_approved', 'applied_date': fields.Datetime.now()})
                rec._send_mail_to_hr()

    def action_manager_approve(self):
        for rec in self:
            if rec.state != 'waiting_manager':
                raise UserError("Only leaves waiting for manager approval can be approved here.")
            manager_user = rec._get_employee_manager_user()
            if manager_user and self.env.user != manager_user:
                raise UserError("Only the direct manager of this employee can approve this request.")
            rec.write({'state': 'manager_approved'})
            rec._send_mail_to_hr()

    def action_manager_reject_wizard(self):
        self.ensure_one()
        manager_user = self._get_employee_manager_user()
        if manager_user and self.env.user != manager_user:
            raise UserError("Only the direct manager of this employee can reject this request.")
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject with Remarks',
            'res_model': 'leave.manager.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id},
        }

    def action_open_approve_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Approve Leave',
            'res_model': 'leave.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_leave_id': self.id}
        }

    def action_reject(self):
        for rec in self:
            if rec.state == 'approved' and rec.balance_deducted:
                LeaveBalance = self.env['leave.balance']
                first_of_month = rec.start_date.replace(day=1)
                balance_record = LeaveBalance.search([
                    ('user_id', '=', rec.user_id.id),
                    ('leave_type_id', '=', rec.leave_type_id.id),
                    ('date', '=', first_of_month)
                ], limit=1)
                if balance_record:
                    if rec.leave_type_id.is_permission:
                        balance_record.balance += rec.hours_requested
                    else:
                        balance_record.balance += rec.days_requested
            rec.write({'balance_deducted': False, 'state': 'rejected'})

    def _send_mail_to_manager(self, manager_user):
        if not manager_user.email:
            return
        leave_type = self.leave_type_id.name
        duration = (f"{self.hours_requested} hrs" if self.leave_type_id.is_permission
                    else ("Half Day (0.5)" if self.is_half_day else f"{self.days_requested} day(s)"))
        date_info = str(self.start_date)
        if self.end_date and self.end_date != self.start_date:
            date_info += f" to {self.end_date}"
        body_html = f"""
            <p>Dear {manager_user.name},</p>
            <p><strong>{self.user_id.name}</strong> has submitted a leave request requiring your approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Leave Type</b></td><td style="padding:4px 10px;">{leave_type}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Date</b></td><td style="padding:4px 10px;">{date_info}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Duration</b></td><td style="padding:4px 10px;">{duration}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Reason</b></td><td style="padding:4px 10px;">{self.reason or '-'}</td></tr>
            </table>
            <p>Please log in and go to <b>Leave → Team Approval</b> to approve or reject.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Leave Approval Needed — {self.user_id.name} ({leave_type})",
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
        leave_type = self.leave_type_id.name
        duration = (f"{self.hours_requested} hrs" if self.leave_type_id.is_permission
                    else ("Half Day (0.5)" if self.is_half_day else f"{self.days_requested} day(s)"))
        date_info = str(self.start_date)
        if self.end_date and self.end_date != self.start_date:
            date_info += f" to {self.end_date}"
        body_html = f"""
            <p>Dear HR,</p>
            <p>The leave request from <strong>{self.user_id.name}</strong> has been approved by the department manager and requires your final approval:</p>
            <table style="border-collapse:collapse;">
                <tr><td style="padding:4px 10px;"><b>Leave Type</b></td><td style="padding:4px 10px;">{leave_type}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Date</b></td><td style="padding:4px 10px;">{date_info}</td></tr>
                <tr><td style="padding:4px 10px;"><b>Duration</b></td><td style="padding:4px 10px;">{duration}</td></tr>
            </table>
            <p>Please go to <b>Leave → Team Approval</b> to proceed.</p>
        """
        self.env['mail.mail'].sudo().create({
            'subject': f"Leave Ready for HR Approval — {self.user_id.name}",
            'body_html': body_html,
            'email_to': ','.join(hr_emails),
            'auto_delete': True,
        }).send()

    def write(self, vals):
        protected = {k for k in vals if k not in ('state', 'balance_deducted', 'paid', 'manager_remarks', 'applied_date')}
        if protected:
            for rec in self:
                if rec.state in ['approved', 'rejected']:
                    raise UserError("You cannot modify a leave request that is already approved or rejected.")
        return super(LeaveRequest, self).write(vals)
