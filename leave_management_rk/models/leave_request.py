from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import timedelta

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
    attachment = fields.Binary(string='Attachment')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('requested', 'Requested'),
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
            # Fall back to today if start_date not yet selected
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

            rec.state = 'requested'
            rec._notify_hr_managers()

    def _notify_hr_managers(self):
        hr_group = self.env.ref('leave_management_rk.group_hr_manager', raise_if_not_found=False)
        if not hr_group:
            return
        hr_emails = [u.email for u in hr_group.users if u.email]
        if not hr_emails:
            return

        leave_type = self.leave_type_id.name
        if self.leave_type_id.is_permission:
            duration = f"{self.hours_requested} hrs"
        elif self.is_half_day:
            duration = "Half Day (0.5)"
        else:
            duration = f"{self.days_requested} day(s)"

        date_info = f"{self.start_date}"
        if self.end_date and self.end_date != self.start_date:
            date_info += f" to {self.end_date}"

        body_html = f"""
            <p>Dear HR,</p>
            <p><strong>{self.user_id.name}</strong> has submitted a leave request awaiting your approval:</p>
            <table style="border-collapse:collapse; width:100%;">
                <tr><td style="padding:4px 8px;"><strong>Leave Type</strong></td><td style="padding:4px 8px;">{leave_type}</td></tr>
                <tr><td style="padding:4px 8px;"><strong>Date</strong></td><td style="padding:4px 8px;">{date_info}</td></tr>
                <tr><td style="padding:4px 8px;"><strong>Duration</strong></td><td style="padding:4px 8px;">{duration}</td></tr>
                {"<tr><td style='padding:4px 8px;'><strong>Reason</strong></td><td style='padding:4px 8px;'>" + (self.reason or '-') + "</td></tr>"}
            </table>
            <p>Please log in to review and approve or reject this request.</p>
            <p>Regards,<br/>Leave Management System</p>
        """

        self.env['mail.mail'].sudo().create({
            'subject': f"Leave Request - {self.user_id.name} ({leave_type})",
            'body_html': body_html,
            'email_to': ','.join(hr_emails),
            'auto_delete': True,
        }).send()

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
                rec.balance_deducted = False
            rec.state = 'rejected'

    def write(self, vals):
        for rec in self:
            if rec.state in ['approved', 'rejected']:
                raise UserError("You cannot modify a leave request that is already approved or rejected.")
        return super(LeaveRequest, self).write(vals)
