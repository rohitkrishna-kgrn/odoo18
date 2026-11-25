from odoo import fields, models

SEND_STATUS = [
    ('pending', 'Pending'),
    ('queued', 'Queued'),
    ('sent', 'Sent'),
    ('failed', 'Failed'),
    ('no_email', 'No Employee Email'),
    ('resend', 'Awaiting Resend'),
]


class PayrollCountryLineLeave(models.Model):
    _name = 'payroll.country.line.leave'
    _description = 'Payroll Line - Approved Leave'
    _order = 'date_from, id'

    line_id = fields.Many2one('payroll.country.line', required=True, ondelete='cascade', index=True)
    leave_request_id = fields.Many2one('leave.request', string='Leave Request', ondelete='set null')
    leave_type = fields.Char(string='Leave Type')
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    is_half_day = fields.Boolean(string='Half Day')
    days_in_period = fields.Float(string='Days in Period', digits=(16, 2),
                                  help="Working days of this leave inside the payroll period "
                                       "(Sundays and public holidays are paid separately).")
    treatment = fields.Selection([
        ('paid', 'Paid Leave'),
        ('unpaid', 'Unpaid (Loss of Pay)'),
        ('permission', 'Permission (hours)'),
        ('sick_dubai', 'Dubai Sick Leave (Full/Half Pay)'),
    ], string='Payroll Treatment')
    state = fields.Char(string='Status')


class PayrollCountryChangeLog(models.Model):
    _name = 'payroll.country.change.log'
    _description = 'Payroll Manual Change'
    _order = 'id desc'

    line_id = fields.Many2one('payroll.country.line', required=True, ondelete='cascade', index=True)
    batch_id = fields.Many2one(related='line_id.batch_id', store=True)
    employee_name = fields.Char(related='line_id.employee_name')
    field_name = fields.Char(string='Field')
    field_label = fields.Char(string='Value')
    old_value = fields.Char(string='Old')
    new_value = fields.Char(string='New')
    calculated_value = fields.Char(string='Calculated')
    synced_to = fields.Char(string='Also Updated In',
                            help="The typed value was written to this Employee / Contract record too.")
    user_id = fields.Many2one('res.users', string='Changed By', default=lambda self: self.env.user)
    date = fields.Datetime(string='Changed On', default=fields.Datetime.now)


class PayrollCountryExcluded(models.Model):
    _name = 'payroll.country.excluded'
    _description = 'Payroll - Employee Not Fetched'
    _order = 'employee_name'

    batch_id = fields.Many2one('payroll.country.batch', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee Record', ondelete='set null')
    employee_name = fields.Char(string='Employee')
    company_name = fields.Char(string='Company')
    contract_ref = fields.Char(string='Contract')
    reason = fields.Char(string='Reason Not Fetched')


class PayrollCountryNotifyLog(models.Model):
    _name = 'payroll.country.notify.log'
    _description = 'Payroll Notification History'
    _order = 'id desc'

    batch_id = fields.Many2one('payroll.country.batch', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([
        ('submitted', 'Approval Request - Payroll Admin'),
        ('approved_officer', 'Approved - Payroll Officers & Managers'),
        ('rejected', 'Rejected - Payroll Officers & Managers'),
        ('resubmit', 'Resubmission Requested - Preparer'),
    ], required=True)
    round = fields.Integer(string='Submission', default=1)
    user_id = fields.Many2one('res.users', string='Recipient', required=True)
    email_to = fields.Char(string='Email')
    mail_id = fields.Many2one('mail.mail', string='Mail', ondelete='set null')
    mail_state = fields.Selection(related='mail_id.state', string='Mail Status')
    date = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('notify_once', 'unique(batch_id, kind, round, user_id)',
         'This notification was already sent to this user.'),
    ]


class PayrollPayslipSendLog(models.Model):
    _name = 'payroll.payslip.send.log'
    _description = 'Payslip Email History'
    _order = 'id desc'

    line_id = fields.Many2one('payroll.country.line', required=True, ondelete='cascade', index=True)
    batch_id = fields.Many2one(related='line_id.batch_id', store=True)
    employee_name = fields.Char(related='line_id.employee_name')
    payslip_ref = fields.Char(string='Payslip')
    email_to = fields.Char(string='Recipient Email')
    status = fields.Selection(SEND_STATUS, string='Status', required=True)
    attempt = fields.Integer(default=1)
    mail_id = fields.Many2one('mail.mail', string='Mail', ondelete='set null', index=True)
    mail_message_id = fields.Many2one('mail.message', string='Mail Message', ondelete='set null')
    sent_date = fields.Datetime(string='Sent On')
    failure_reason = fields.Text(string='Failure Reason')
    user_id = fields.Many2one('res.users', string='Sent By', default=lambda self: self.env.user)
    date = fields.Datetime(string='Requested On', default=fields.Datetime.now)
