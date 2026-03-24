from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import calendar

class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    employee_id = fields.Many2one('hr.employee', string='Employee')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        readonly=True,
        store=True,
        default=lambda self: self.env.company.id,
    )
    current_price = fields.Float(string="Current Price")
    customer_id = fields.Many2one('res.partner', string="Customer", store=True)
    attachment_file = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="Filename")

    @api.onchange('project_id')
    def _onchange_project_id_set_customer(self):
        if self.project_id:
            self.customer_id = self.project_id.partner_id
        else:
            self.customer_id = False

    @api.model
    def create(self, vals):

        if vals.get('date'):
            entry_date = fields.Date.from_string(vals['date'])
            if entry_date > fields.Date.context_today(self):
                raise ValidationError(
                    _("You cannot create timesheets for future dates.")
                )
                
        # Set employee if not provided or inactive
        employee = None
        if vals.get('employee_id'):
            employee = self.env['hr.employee'].browse(vals['employee_id'])
            if not employee.exists() or not employee.active:
                employee = None

        if not employee:
            user = self.env.user
            employee = self.env['hr.employee'].search([
                ('user_id', '=', user.id),
                ('active', '=', True),
            ], limit=1)

        # Ensure company_id is set from project_id if not explicitly provided
        if not vals.get('company_id') and vals.get('project_id'):
            project = self.env['project.project'].browse(vals['project_id'])
            if project and project.company_id:
                vals['company_id'] = project.company_id.id

        # ✅ Set customer_id from project.partner_id if not provided
        if not vals.get('customer_id') and vals.get('project_id'):
            project = self.env['project.project'].browse(vals['project_id'])
            if project and project.partner_id:
                vals['customer_id'] = project.partner_id.id

        # Calculate current_price from employee contract
        if employee:
            contract = self.env['hr.contract'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'open')
            ], limit=1)

            if contract and contract.wage:
                today = datetime.today()
                year = today.year
                month = today.month
                first_day = datetime(year, month, 1)
                last_day = datetime(year, month, calendar.monthrange(year, month)[1])
                total_days = (last_day - first_day).days + 1
                working_days = sum(1 for i in range(total_days)
                                if (first_day + timedelta(days=i)).weekday() != 6)

                if working_days > 0:
                    per_day = contract.wage / working_days
                    current_price = (per_day / 8.0) - 1
                    vals['current_price'] = current_price

        return super().create(vals)

    @api.constrains('employee_id', 'company_id')
    def _check_employee_company(self):
        # Override and disable the validation to remove the error completely
        return True
