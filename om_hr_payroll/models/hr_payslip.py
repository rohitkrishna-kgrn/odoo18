import babel
from datetime import date, datetime, time, timedelta
from dateutil.relativedelta import relativedelta
from pytz import timezone
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.addons.leave_management_rk.models.leave_period import current_leave_month_bounds
import base64
from io import BytesIO
from calendar import SUNDAY, SATURDAY
import xlsxwriter
from pytz import UTC

class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _description = 'Pay Slip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    struct_id = fields.Many2one('hr.payroll.structure', string='Structure',
        help='Defines the rules that have to be applied to this payslip, accordingly '
             'to the contract chosen. If you let empty the field contract, this field isn\'t '
             'mandatory anymore and thus the rules applied will be all the rules set on the '
             'structure of all contracts of the employee valid for the chosen period')
    name = fields.Char(string='Payslip Name')
    number = fields.Char(string='Reference', copy=False)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    date_from = fields.Date(string='Date From', required=True,
        default=lambda self: current_leave_month_bounds()[0])
    date_to = fields.Date(string='Date To', required=True,
        default=lambda self: current_leave_month_bounds()[1])
    # this is chaos: 4 states are defined, 3 are used ('verify' isn't) and 5 exist ('confirm' seems to have existed)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verify', 'Waiting'),
        ('done', 'Done'),
        ('cancel', 'Rejected'),
    ], string='Status', index=True, readonly=True, copy=False, default='draft',
        help="""* When the payslip is created the status is \'Draft\'
                \n* If the payslip is under verification, the status is \'Waiting\'.
                \n* If the payslip is confirmed then status is set to \'Done\'.
                \n* When user cancel payslip the status is \'Rejected\'.""")
    line_ids = fields.One2many('hr.payslip.line', 'slip_id', string='Payslip Lines')
    company_id = fields.Many2one(
        'res.company', string='Company', copy=False,
        default=lambda self: self.env.company
    )
    worked_days_line_ids = fields.One2many(
        'hr.payslip.worked_days', 'payslip_id',
        string='Payslip Worked Days', copy=True
    )
    input_line_ids = fields.One2many(
        'hr.payslip.input', 'payslip_id',
        string='Payslip Inputs', copy=True
    )
    paid = fields.Boolean(string='Made Payment Order ? ', copy=False)
    note = fields.Text(string='Internal Note')
    contract_id = fields.Many2one('hr.contract', string='Contract')
    details_by_salary_rule_category = fields.One2many('hr.payslip.line',
        compute='_compute_details_by_salary_rule_category', string='Details by Salary Rule Category')
    credit_note = fields.Boolean(string='Credit Note',
        help="Indicates this payslip has a refund of another")
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Payslip Batches', copy=False)
    payslip_count = fields.Integer(compute='_compute_payslip_count', string="Payslip Computation Details")
    work_days = fields.Float(compute='_compute_lop_paid_days', string='Work Days')
    lop_days = fields.Float(compute='_compute_lop_paid_days', string='LOP Days')
    paid_days = fields.Float(compute='_compute_lop_paid_days', string='Paid Days')

    @api.depends('worked_days_line_ids.number_of_days')
    def _compute_lop_paid_days(self):
        for slip in self:
            by_code = {line.code: line.number_of_days for line in slip.worked_days_line_ids}
            total = by_code.get('WORK100', 0.0)
            accounted = by_code.get('PRESENT', 0.0) + by_code.get('LEAVE', 0.0) \
                + by_code.get('SUNDAY', 0.0) + by_code.get('PH', 0.0)
            slip.work_days = total
            slip.lop_days = max(total - accounted, 0.0)
            slip.paid_days = total - slip.lop_days

    def _compute_details_by_salary_rule_category(self):
        for payslip in self:
            payslip.details_by_salary_rule_category = payslip.mapped('line_ids').filtered(lambda line: line.category_id)

    def _compute_payslip_count(self):
        for payslip in self:
            payslip.payslip_count = len(payslip.line_ids)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        if any(self.filtered(lambda payslip: payslip.date_from > payslip.date_to)):
            raise ValidationError(_("Payslip 'Date From' must be earlier 'Date To'."))

    def action_payslip_draft(self):
        return self.write({'state': 'draft'})

    def action_payslip_done(self):
        """Mark payslip as done and send PDF via email without resetting line items."""
        Mail = self.env['mail.mail']
        Attachment = self.env['ir.attachment']
        ReportRef = 'om_hr_payroll.report_payslip'  # Update with your actual report XML ID

        for payslip in self:
            # Set state to done without recomputing worked days or inputs

            employee = payslip.employee_id
            email = employee.work_email

            if not email:
                continue

            # Generate payslip PDF
            pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                report_ref=ReportRef,
                res_ids=[payslip.id]
            )
            pdf_name = f"Payslip_{payslip.number or payslip.name}.pdf"

            # Create attachment
            attachment = Attachment.create({
                'name': pdf_name,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'hr.payslip',
                'res_id': payslip.id,
                'mimetype': 'application/pdf',
            })

            # Email body
            body_html = f"""
                <p>Dear {employee.name},</p>
                <p>Your payslip for the period <strong>{payslip.date_from}</strong>
                to <strong>{payslip.date_to}</strong> is now available.</p>
                <p><strong>Reference:</strong> {payslip.number}</p>
                <p>Please find the attached PDF document for your records.</p>
                <br/>
                <p>Regards,<br/>HR Department</p>
            """

            # Send email
            mail = Mail.create({
                'subject': f"Payslip - {payslip.date_from.strftime('%b %Y')}",
                'body_html': body_html,
                'email_to': email,
                'email_from': payslip.company_id.email or 'no-reply@yourcompany.com',
                'attachment_ids': [(4, attachment.id)],
                'auto_delete': True,
            })
            mail.send()

        return self.write({'state': 'done'})


    def action_payslip_cancel(self):
        # if self.filtered(lambda slip: slip.state == 'done'):
        #     raise UserError(_("Cannot cancel a payslip that is done."))
        return self.write({'state': 'cancel'})

    def refund_sheet(self):
        for payslip in self:
            copied_payslip = payslip.copy({'credit_note': True, 'name': _('Refund: ') + payslip.name})
            copied_payslip.compute_sheet()
            copied_payslip.action_payslip_done()
        form_view_ref = self.env.ref('om_om_hr_payroll.view_hr_payslip_form', False)
        list_view_ref = self.env.ref('om_om_hr_payroll.view_hr_payslip_tree', False)
        return {
            'name': (_("Refund Payslip")),
            'view_mode': 'list, form',
            'view_id': False,
            'view_type': 'form',
            'res_model': 'hr.payslip',
            'type': 'ir.actions.act_window',
            'target': 'current',
            'domain': "[('id', 'in', %s)]" % copied_payslip.ids,
            'views': [(list_view_ref and list_view_ref.id or False, 'list'), (form_view_ref and form_view_ref.id or False, 'form')],
            'context': {}
        }

    def action_send_email(self):
        self.ensure_one()
        ir_model_data = self.env['ir.model.data']
        try:
            template_id = self.env.ref('om_hr_payroll.mail_template_payslip').id
        except ValueError:
            template_id = False
        try:
            compose_form_id = ir_model_data._xmlid_lookup('mail.email_compose_message_wizard_form')[1]

        except ValueError:
            compose_form_id = False
        ctx = {
            'default_model': 'hr.payslip',
            'default_res_ids': self.ids,
            'default_use_template': bool(template_id),
            'default_template_id': template_id,
            'default_composition_mode': 'comment',
        }
        return {
            'name': _('Compose Email'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }

    def check_done(self):
        return True

    def unlink(self):
        if any(self.filtered(lambda payslip: payslip.state not in ('draft', 'cancel'))):
            raise UserError(_('You cannot delete a payslip which is not draft or cancelled!'))
        return super(HrPayslip, self).unlink()

    # TODO move this function into hr_contract module, on hr.employee object
    @api.model
    def get_contract(self, employee, date_from, date_to):
        """
        @param employee: recordset of employee
        @param date_from: date field
        @param date_to: date field
        @return: returns the ids of all the contracts for the given employee that need to be considered for the given dates
        """
        # a contract is valid if it ends between the given dates
        clause_1 = ['&', ('date_end', '<=', date_to), ('date_end', '>=', date_from)]
        # OR if it starts between the given dates
        clause_2 = ['&', ('date_start', '<=', date_to), ('date_start', '>=', date_from)]
        # OR if it starts before the date_from and finish after the date_end (or never finish)
        clause_3 = ['&', ('date_start', '<=', date_from), '|', ('date_end', '=', False), ('date_end', '>=', date_to)]
        clause_final = [('employee_id', '=', employee.id), ('state', '=', 'open'), '|', '|'] + clause_1 + clause_2 + clause_3
        return self.env['hr.contract'].search(clause_final).ids

    def compute_sheet(self):
        for payslip in self:
            number = payslip.number or self.env['ir.sequence'].next_by_code('salary.slip')
            # delete old payslip lines
            payslip.line_ids.unlink()
            # set the list of contract for which the rules have to be applied
            # if we don't give the contract, then the rules to apply should be for all current contracts of the employee
            contract_ids = payslip.contract_id.ids or \
                self.get_contract(payslip.employee_id, payslip.date_from, payslip.date_to)
            if not contract_ids:
                raise ValidationError(_("No running contract found for the employee: %s or no contract in the given period" % payslip.employee_id.name))
            lines = [(0, 0, line) for line in self._get_payslip_lines(contract_ids, payslip.id)]
            payslip.write({'line_ids': lines, 'number': number})
        return True

    @api.model
    def get_worked_day_lines(self, contracts, date_from, date_to):
        LeaveRequest = self.env['leave.request']
        PublicHoliday = self.env['public.holiday']
        Attendance = self.env['hr.attendance']

        worked_days = []

        date_from_dt = fields.Date.to_date(date_from)
        date_to_dt = fields.Date.to_date(date_to)

        # Total days in period (full period, no exclusion)
        total_days_set = {date_from_dt + timedelta(days=i) for i in range((date_to_dt - date_from_dt).days + 1)}

        # Count Sundays in period
        sundays_set = {d for d in total_days_set if d.weekday() == SUNDAY}

        for contract in contracts:
            employee = contract.employee_id
            user = employee.user_id
            if not user:
                continue

            # 1. Paid Leaves (excludes permission leaves which have paid=False)
            paid_leaves = LeaveRequest.search([
                ('user_id', '=', user.id),
                ('state', '=', 'approved'),
                ('paid', '=', True),
                ('start_date', '<=', date_to),
                ('end_date', '>=', date_from),
            ])
            total_leave_days = 0.0
            half_day_leave_dates = set()
            for leave in paid_leaves:
                total_leave_days += leave.days_requested
                if leave.is_half_day and leave.start_date:
                    half_day_leave_dates.add(leave.start_date)

            if total_leave_days:
                worked_days.append({
                    'name': 'Paid Leave',
                    'sequence': 10,
                    'code': 'LEAVE',
                    'number_of_days': total_leave_days,
                    'number_of_hours': total_leave_days * 8,
                    'contract_id': contract.id,
                })

            # 2. Public Holidays
            public_holidays = PublicHoliday.search([
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ])
            public_holiday_dates = {fields.Date.to_date(ph.date) for ph in public_holidays}

            if public_holiday_dates:
                worked_days.append({
                    'name': 'Public Holiday',
                    'sequence': 20,
                    'code': 'PH',
                    'number_of_days': len(public_holiday_dates),
                    'number_of_hours': len(public_holiday_dates) * 8,
                    'contract_id': contract.id,
                })

            # 3. Attendance Days — days with a paid half-day leave count as 0.5
            attendance_records = Attendance.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', datetime.combine(date_from_dt, datetime.min.time()).replace(tzinfo=UTC)),
                ('check_in', '<=', datetime.combine(date_to_dt, datetime.max.time()).replace(tzinfo=UTC)),
            ])
            present_days_set = {att.check_in.astimezone(UTC).date() for att in attendance_records if att.check_in}

            if not present_days_set:
                number_of_days = 0.0
                number_of_hours = 0.0
            else:
                number_of_days = sum(
                    0.5 if d in half_day_leave_dates else 1.0
                    for d in present_days_set
                )
                number_of_hours = number_of_days * 8

            worked_days.append({
                'name': 'Present (Attendance)',
                'sequence': 30,
                'code': 'PRESENT',
                'number_of_days': number_of_days,
                'number_of_hours': number_of_hours,
                'contract_id': contract.id,
            })

            # 3b. Late Login Deduction (0.5 day per late check-in, Asia/Dubai time)
            _DUBAI_TZ = timezone('Asia/Dubai')
            late_login_count = 0
            for att in attendance_records:
                if not att.check_in:
                    continue
                check_in_dubai = att.check_in.replace(tzinfo=UTC).astimezone(_DUBAI_TZ)
                deadline = check_in_dubai.replace(hour=8, minute=50, second=0, microsecond=0)
                if check_in_dubai <= deadline:
                    continue
                date_worked = check_in_dubai.date()
                permissions = LeaveRequest.search([
                    ('user_id', '=', user.id),
                    ('state', '=', 'approved'),
                    ('leave_type_id.is_permission', '=', True),
                    ('start_date', '=', date_worked),
                ])
                permission_hours = sum(permissions.mapped('hours_requested'))
                extended_deadline = deadline + timedelta(hours=permission_hours)
                if check_in_dubai > extended_deadline:
                    late_login_count += 1

            if late_login_count:
                late_deduct_days = late_login_count * 0.5
                worked_days.append({
                    'name': 'Late Login Deduction',
                    'sequence': 35,
                    'code': 'LATE_DEDUCT',
                    'number_of_days': late_deduct_days,
                    'number_of_hours': late_deduct_days * 8,
                    'contract_id': contract.id,
                })

            # 4. Sundays in Period
            worked_days.append({
                'name': 'Sundays',
                'sequence': 40,
                'code': 'SUNDAY',
                'number_of_days': len(sundays_set),
                'number_of_hours': len(sundays_set) * 8,
                'contract_id': contract.id,
            })

            # 5. WORK100 - Total Days in period (full)
            worked_days.append({
                'name': 'Total Days in Period',
                'sequence': 99,
                'code': 'WORK100',
                'number_of_days': len(total_days_set),
                'number_of_hours': len(total_days_set) * 8,
                'contract_id': contract.id,
            })

        return worked_days
        
    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        res = []

        structure_ids = contracts.get_all_structures()
        rule_ids = self.env['hr.payroll.structure'].browse(structure_ids).get_all_rules()
        sorted_rule_ids = [id for id, sequence in sorted(rule_ids, key=lambda x:x[1])]
        inputs = self.env['hr.salary.rule'].browse(sorted_rule_ids).mapped('input_ids')

        for contract in contracts:
            for input in inputs:
                input_data = {
                    'name': input.name,
                    'code': input.code,
                    'contract_id': contract.id,
                }
                res += [input_data]
        return res

    @api.model
    def _get_payslip_lines(self, contract_ids, payslip_id):
        def _sum_salary_rule_category(localdict, category, amount):
            if category.parent_id:
                localdict = _sum_salary_rule_category(localdict, category.parent_id, amount)
            localdict['categories'].dict[category.code] = category.code in localdict['categories'].dict and localdict['categories'].dict[category.code] + amount or amount
            return localdict

        class BrowsableObject(object):
            def __init__(self, employee_id, dict, env):
                self.employee_id = employee_id
                self.dict = dict
                self.env = env

            def __getattr__(self, attr):
                return attr in self.dict and self.dict.__getitem__(attr) or 0.0

        class InputLine(BrowsableObject):
            """a class that will be used into the python code, mainly for usability purposes"""
            def sum(self, code, from_date, to_date=None):
                if to_date is None:
                    to_date = fields.Date.today()
                self.env.cr.execute("""
                    SELECT sum(amount) as sum
                    FROM hr_payslip as hp, hr_payslip_input as pi
                    WHERE hp.employee_id = %s AND hp.state = 'done'
                    AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pi.payslip_id AND pi.code = %s""",
                    (self.employee_id, from_date, to_date, code))
                return self.env.cr.fetchone()[0] or 0.0

        class WorkedDays(BrowsableObject):
            """a class that will be used into the python code, mainly for usability purposes"""
            def _sum(self, code, from_date, to_date=None):
                if to_date is None:
                    to_date = fields.Date.today()
                self.env.cr.execute("""
                    SELECT sum(number_of_days) as number_of_days, sum(number_of_hours) as number_of_hours
                    FROM hr_payslip as hp, hr_payslip_worked_days as pi
                    WHERE hp.employee_id = %s AND hp.state = 'done'
                    AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pi.payslip_id AND pi.code = %s""",
                    (self.employee_id, from_date, to_date, code))
                return self.env.cr.fetchone()

            def sum(self, code, from_date, to_date=None):
                res = self._sum(code, from_date, to_date)
                return res and res[0] or 0.0

            def sum_hours(self, code, from_date, to_date=None):
                res = self._sum(code, from_date, to_date)
                return res and res[1] or 0.0

        class Payslips(BrowsableObject):
            """a class that will be used into the python code, mainly for usability purposes"""

            def sum(self, code, from_date, to_date=None):
                if to_date is None:
                    to_date = fields.Date.today()
                self.env.cr.execute("""SELECT sum(case when hp.credit_note = False then (pl.total) else (-pl.total) end)
                            FROM hr_payslip as hp, hr_payslip_line as pl
                            WHERE hp.employee_id = %s AND hp.state = 'done'
                            AND hp.date_from >= %s AND hp.date_to <= %s AND hp.id = pl.slip_id AND pl.code = %s""",
                            (self.employee_id, from_date, to_date, code))
                res = self.env.cr.fetchone()
                return res and res[0] or 0.0

        #we keep a dict with the result because a value can be overwritten by another rule with the same code
        result_dict = {}
        rules_dict = {}
        worked_days_dict = {}
        inputs_dict = {}
        blacklist = []
        payslip = self.env['hr.payslip'].browse(payslip_id)
        for worked_days_line in payslip.worked_days_line_ids:
            worked_days_dict[worked_days_line.code] = worked_days_line
        for input_line in payslip.input_line_ids:
            inputs_dict[input_line.code] = input_line

        categories = BrowsableObject(payslip.employee_id.id, {}, self.env)
        inputs = InputLine(payslip.employee_id.id, inputs_dict, self.env)
        worked_days = WorkedDays(payslip.employee_id.id, worked_days_dict, self.env)
        payslips = Payslips(payslip.employee_id.id, payslip, self.env)
        rules = BrowsableObject(payslip.employee_id.id, rules_dict, self.env)

        baselocaldict = {'categories': categories, 'rules': rules, 'payslip': payslips, 'worked_days': worked_days, 'inputs': inputs}
        #get the ids of the structures on the contracts and their parent id as well
        contracts = self.env['hr.contract'].browse(contract_ids)
        if len(contracts) == 1 and payslip.struct_id:
            structure_ids = list(set(payslip.struct_id._get_parent_structure().ids))
        else:
            structure_ids = contracts.get_all_structures()
        #get the rules of the structure and thier children
        rule_ids = self.env['hr.payroll.structure'].browse(structure_ids).get_all_rules()
        #run the rules by sequence
        sorted_rule_ids = [id for id, sequence in sorted(rule_ids, key=lambda x:x[1])]
        sorted_rules = self.env['hr.salary.rule'].browse(sorted_rule_ids)

        for contract in contracts:
            employee = contract.employee_id
            localdict = dict(baselocaldict, employee=employee, contract=contract)
            for rule in sorted_rules:
                key = rule.code + '-' + str(contract.id)
                localdict['result'] = None
                localdict['result_qty'] = 1.0
                localdict['result_rate'] = 100
                #check if the rule can be applied
                if rule._satisfy_condition(localdict) and rule.id not in blacklist:
                    #compute the amount of the rule
                    amount, qty, rate = rule._compute_rule(localdict)
                    #check if there is already a rule computed with that code
                    previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                    #set/overwrite the amount computed for this rule in the localdict
                    tot_rule = contract.company_id.currency_id.round(amount * qty * rate / 100.0)
                    localdict[rule.code] = tot_rule
                    rules_dict[rule.code] = rule
                    #sum the amount for its salary category
                    localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
                    #create/overwrite the rule in the temporary results
                    result_dict[key] = {
                        'salary_rule_id': rule.id,
                        'contract_id': contract.id,
                        'name': rule.name,
                        'code': rule.code,
                        'category_id': rule.category_id.id,
                        'sequence': rule.sequence,
                        'appears_on_payslip': rule.appears_on_payslip,
                        'condition_select': rule.condition_select,
                        'condition_python': rule.condition_python,
                        'condition_range': rule.condition_range,
                        'condition_range_min': rule.condition_range_min,
                        'condition_range_max': rule.condition_range_max,
                        'amount_select': rule.amount_select,
                        'amount_fix': rule.amount_fix,
                        'amount_python_compute': rule.amount_python_compute,
                        'amount_percentage': rule.amount_percentage,
                        'amount_percentage_base': rule.amount_percentage_base,
                        'register_id': rule.register_id.id,
                        'amount': amount,
                        'employee_id': contract.employee_id.id,
                        'quantity': qty,
                        'rate': rate,
                    }
                else:
                    #blacklist this rule and its children
                    blacklist += [id for id, seq in rule._recursive_search_of_rules()]

        return list(result_dict.values())

    # YTI TODO To rename. This method is not really an onchange, as it is not in any view
    # employee_id and contract_id could be browse records
    def onchange_employee_id(self, date_from, date_to, employee_id=False, contract_id=False):
        #defaults
        res = {
            'value': {
                'line_ids': [],
                #delete old input lines
                'input_line_ids': [(2, x,) for x in self.input_line_ids.ids],
                #delete old worked days lines
                'worked_days_line_ids': [(2, x,) for x in self.worked_days_line_ids.ids],
                #'details_by_salary_head':[], TODO put me back
                'name': '',
                'contract_id': False,
                'struct_id': False,
            }
        }
        if (not employee_id) or (not date_from) or (not date_to):
            return res
        ttyme = datetime.combine(fields.Date.from_string(date_from), time.min)
        employee = self.env['hr.employee'].browse(employee_id)
        locale = self.env.context.get('lang') or 'en_US'
        res['value'].update({
            'name': _('Salary Slip of %s for %s') % (employee.name, tools.ustr(babel.dates.format_date(date=ttyme, format='MMMM-y', locale=locale))),
            'company_id': employee.company_id.id,
        })

        if not self.env.context.get('contract'):
            #fill with the first contract of the employee
            contract_ids = self.get_contract(employee, date_from, date_to)
        else:
            if contract_id:
                #set the list of contract for which the input have to be filled
                contract_ids = [contract_id]
            else:
                #if we don't give the contract, then the input to fill should be for all current contracts of the employee
                contract_ids = self.get_contract(employee, date_from, date_to)

        if not contract_ids:
            return res
        contract = self.env['hr.contract'].browse(contract_ids[0])
        res['value'].update({
            'contract_id': contract.id
        })
        struct = contract.struct_id
        if not struct:
            return res
        res['value'].update({
            'struct_id': struct.id,
        })
        #computation of the salary input
        contracts = self.env['hr.contract'].browse(contract_ids)
        worked_days_line_ids = self.get_worked_day_lines(contracts, date_from, date_to)
        input_line_ids = self.get_inputs(contracts, date_from, date_to)
        res['value'].update({
            'worked_days_line_ids': worked_days_line_ids,
            'input_line_ids': input_line_ids,
        })
        return res

    @api.onchange('employee_id', 'date_from', 'date_to')
    def onchange_employee(self):
        self.ensure_one()
        if not self.employee_id or not self.date_from or not self.date_to:
            return

        employee = self.employee_id
        date_from = self.date_from
        date_to = self.date_to

        # Set payslip name
        ttyme = datetime.combine(fields.Date.from_string(date_from), time.min)
        locale = self.env.context.get('lang') or 'en_US'
        self.name = _('Salary Slip of %s for %s') % (
            employee.name,
            tools.ustr(babel.dates.format_date(date=ttyme, format='MMMM-y', locale=locale))
        )
        self.company_id = employee.company_id

        # Always fetch contract based on current employee and date range
        contract_ids = self.get_contract(employee, date_from, date_to)
        if not contract_ids:
            return

        self.contract_id = self.env['hr.contract'].browse(contract_ids[0])

        if not self.contract_id.struct_id:
            return

        self.struct_id = self.contract_id.struct_id

        # Refresh worked days
        contracts = self.env['hr.contract'].browse(contract_ids)
        self.worked_days_line_ids = [(5, 0, 0)]  # Clear previous
        worked_days_line_ids = self.get_worked_day_lines(contracts, date_from, date_to)
        worked_days_lines = self.worked_days_line_ids.browse([])
        for r in worked_days_line_ids:
            worked_days_lines += worked_days_lines.new(r)
        self.worked_days_line_ids = worked_days_lines

        # Refresh inputs
        self.input_line_ids = [(5, 0, 0)]  # Clear previous
        input_line_ids = self.get_inputs(contracts, date_from, date_to)
        input_lines = self.input_line_ids.browse([])
        for r in input_line_ids:
            input_lines += input_lines.new(r)
        self.input_line_ids = input_lines


    @api.onchange('contract_id')
    def onchange_contract(self):
        if not self.contract_id:
            self.struct_id = False
        self.with_context(contract=True).onchange_employee()
        return

    def get_salary_line_total(self, code):
        self.ensure_one()
        line = self.line_ids.filtered(lambda line: line.code == code)
        if line:
            return line[0].total
        else:
            return 0.0


class HrPayslipLine(models.Model):
    _name = 'hr.payslip.line'
    _inherit = 'hr.salary.rule'
    _description = 'Payslip Line'
    _order = 'contract_id, sequence'

    slip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, ondelete='cascade')
    salary_rule_id = fields.Many2one('hr.salary.rule', string='Rule', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    contract_id = fields.Many2one('hr.contract', string='Contract', required=True, index=True)
    rate = fields.Float(string='Rate (%)', default=100.0)
    amount = fields.Float()
    quantity = fields.Float(default=1.0)
    total = fields.Float(compute='_compute_total', string='Total')

    @api.depends('quantity', 'amount', 'rate')
    def _compute_total(self):
        for line in self:
            line.total = float(line.quantity) * line.amount * line.rate / 100

    @api.onchange('amount', 'quantity', 'rate')
    def _onchange_recompute_net_salary(self):
        """Manually editing any line's Amount/Quantity/Rate in the Salary Computation
        list should keep the Net Salary line in sync, mirroring the NET rule's own
        formula (categories.BASIC + categories.ALW + categories.DED) instead of only
        reflecting whatever was computed the last time Compute Sheet ran."""
        if self.code == 'NET':
            return
        lines = self.slip_id.line_ids
        net_line = lines.filtered(lambda l: l.code == 'NET')
        if not net_line:
            return
        basic = sum(lines.filtered(lambda l: l.category_id.code == 'BASIC').mapped('total'))
        alw = sum(lines.filtered(lambda l: l.category_id.code == 'ALW').mapped('total'))
        ded = sum(lines.filtered(lambda l: l.category_id.code == 'DED').mapped('total'))
        net_line[0].amount = basic + alw + ded

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if 'employee_id' not in values or 'contract_id' not in values:
                payslip = self.env['hr.payslip'].browse(values.get('slip_id'))
                values['employee_id'] = values.get('employee_id') or payslip.employee_id.id
                values['contract_id'] = values.get('contract_id') or payslip.contract_id and payslip.contract_id.id
                if not values['contract_id']:
                    raise UserError(_('You must set a contract to create a payslip line.'))
        return super(HrPayslipLine, self).create(vals_list)


class HrPayslipWorkedDays(models.Model):
    _name = 'hr.payslip.worked_days'
    _description = 'Payslip Worked Days'
    _order = 'payslip_id, sequence'

    name = fields.Char(string='Description', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(required=True, index=True, default=10)
    code = fields.Char(required=True, help="The code that can be used in the salary rules")
    number_of_days = fields.Float(string='Number of Days')
    number_of_hours = fields.Float(string='Number of Hours')
    contract_id = fields.Many2one('hr.contract', string='Contract', required=True,
        help="The contract for which applied this input")


class HrPayslipInput(models.Model):
    _name = 'hr.payslip.input'
    _description = 'Payslip Input'
    _order = 'payslip_id, sequence'

    name = fields.Char(string='Description', required=True)
    payslip_id = fields.Many2one('hr.payslip', string='Pay Slip', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(required=True, index=True, default=10)
    code = fields.Char(required=True, help="The code that can be used in the salary rules")
    amount = fields.Float(help="It is used in computation. For e.g. A rule for sales having "
                               "1% commission of basic salary for per product can defined in expression "
                               "like result = inputs.SALEURO.amount * contract.wage*0.01.")
    contract_id = fields.Many2one('hr.contract', string='Contract', required=True,
        help="The contract for which applied this input")


class HrPayslipRun(models.Model):
    _name = 'hr.payslip.run'
    _description = 'Payslip Batches'

    name = fields.Char(required=True)
    slip_ids = fields.One2many('hr.payslip', 'payslip_run_id', string='Payslips')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
        ('close', 'Close'),
    ], string='Status', index=True, readonly=True, copy=False, default='draft')
    date_start = fields.Date(
        string='Date From', required=True,
        default=lambda self: current_leave_month_bounds()[0]
    )
    date_end = fields.Date(
        string='Date To', required=True,
        default=lambda self: current_leave_month_bounds()[1]
    )
    credit_note = fields.Boolean(
        string='Credit Note',
        help="If its checked, indicates that all payslips generated from here are refund payslips."
    )

    def draft_payslip_run(self):
        return self.write({'state': 'draft'})

    def close_payslip_run(self):
        return self.write({'state': 'close'})

    def done_payslip_run(self):
        """Mark payslips as done and email them with PDF attached to each employee."""
        Mail = self.env['mail.mail']
        Attachment = self.env['ir.attachment']
        ReportRef = 'om_hr_payroll.report_payslip'  # The XML ID of your payslip PDF report

        for payslip in self.slip_ids:
            payslip.action_payslip_done()

            employee = payslip.employee_id
            email = employee.work_email

            if not email:
                continue  # Skip if no email

            # ✅ Render the payslip PDF correctly using ir.actions.report
            pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                report_ref=ReportRef,
                res_ids=[payslip.id]
            )
            pdf_name = f"Payslip_{payslip.number or payslip.name}.pdf"

            # Create the attachment
            attachment = Attachment.create({
                'name': pdf_name,
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': 'hr.payslip',
                'res_id': payslip.id,
                'mimetype': 'application/pdf',
            })

            # Email body
            body_html = f"""
                <p>Dear {employee.name},</p>
                <p>Your payslip for the period <strong>{payslip.date_from.strftime('%Y-%m-%d')}</strong>
                to <strong>{payslip.date_to.strftime('%Y-%m-%d')}</strong> is now available.</p>
                <p><strong>Reference:</strong> {payslip.number}</p>
                <p>Please find the attached PDF document for your records.</p>
                <br/>
                <p>Regards,<br/>
                HR Department</p>
            """

            # Create and send the email
            mail = Mail.create({
                'subject': f"Payslip - {payslip.date_from.strftime('%b %Y')}",
                'body_html': body_html,
                'email_to': email,
                'email_from': payslip.company_id.email or 'no-reply@yourcompany.com',
                'attachment_ids': [(4, attachment.id)],
                'auto_delete': True,
            })

            mail.send()

        return self.write({'state': 'done'})

    def unlink(self):
        for rec in self:
            if rec.state == 'done':
                raise ValidationError(_('You Cannot Delete Done Payslips Batches'))
        return super(HrPayslipRun, self).unlink()

    def action_export_payslips_xlsx(self):
        self.ensure_one()
        payslips = self.slip_ids

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        header_format = workbook.add_format({'bold': True, 'bg_color': '#DCE6F1'})
        bold = workbook.add_format({'bold': True})

        for slip in payslips:
            sheet_name = (slip.number or slip.name or 'Payslip')[:31]  # Excel sheet name limit
            sheet = workbook.add_worksheet(sheet_name)

            row = 0

            # Payslip Header
            sheet.write(row, 0, 'Employee Name', bold)
            sheet.write(row, 1, slip.employee_id.name or '')
            row += 1

            sheet.write(row, 0, 'Job Title', bold)
            sheet.write(row, 1, slip.employee_id.job_id.name or '')
            row += 1

            sheet.write(row, 0, 'Email', bold)
            sheet.write(row, 1, slip.employee_id.work_email or '')
            row += 1

            sheet.write(row, 0, 'ID Number', bold)
            sheet.write(row, 1, slip.employee_id.identification_id or '')
            row += 1

            sheet.write(row, 0, 'Bank Account', bold)
            sheet.write(row, 1, slip.employee_id.bank_account_id.acc_number or '')
            row += 1

            sheet.write(row, 0, 'Date From', bold)
            sheet.write(row, 1, slip.date_from.strftime('%Y-%m-%d') if slip.date_from else '')
            row += 1

            sheet.write(row, 0, 'Date To', bold)
            sheet.write(row, 1, slip.date_to.strftime('%Y-%m-%d') if slip.date_to else '')
            row += 2

            # Payslip Lines Table
            sheet.write(row, 0, 'Code', header_format)
            sheet.write(row, 1, 'Name', header_format)
            sheet.write(row, 2, 'Amount', header_format)
            sheet.write(row, 3, 'Total', header_format)
            row += 1

            for line in slip.line_ids.filtered(lambda l: l.appears_on_payslip):
                sheet.write(row, 0, line.code)
                sheet.write(row, 1, line.name)
                sheet.write(row, 2, line.amount)
                sheet.write(row, 3, line.total)
                row += 1

            row += 2
            sheet.write(row, 0, "Worked Day Lines", bold)
            row += 1

            # Worked Days Header
            sheet.write(row, 0, 'Name', header_format)
            sheet.write(row, 1, 'Code', header_format)
            sheet.write(row, 2, 'Days', header_format)
            sheet.write(row, 3, 'Hours', header_format)
            row += 1

            # Compute worked days using your provided method
            worked_days = self._compute_worked_days_for_contracts(slip.contract_id, slip.date_from, slip.date_to)
            for wd in worked_days:
                sheet.write(row, 0, wd.get('name'))
                sheet.write(row, 1, wd.get('code'))
                sheet.write(row, 2, wd.get('number_of_days'))
                sheet.write(row, 3, wd.get('number_of_hours'))
                row += 1

        workbook.close()
        output.seek(0)
        file_data = output.read()
        output.close()

        filename = f"Payslip_Batch_{self.name.replace(' ', '_')}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        download_url = f'/web/content/{attachment.id}?download=true'

        return {
            "type": "ir.actions.act_url",
            "url": download_url,
            "target": "new",
        }

    def _compute_worked_days_for_contracts(self, contract, date_from, date_to):
        LeaveRequest = self.env['leave.request']
        PublicHoliday = self.env['public.holiday']
        Attendance = self.env['hr.attendance']

        worked_days = []

        date_from_dt = fields.Date.to_date(date_from)
        date_to_dt = fields.Date.to_date(date_to)

        # Total days in period (full period, no exclusion)
        total_days_set = {date_from_dt + timedelta(days=i) for i in range((date_to_dt - date_from_dt).days + 1)}

        # Count Sundays
        sundays_set = {d for d in total_days_set if d.weekday() == SUNDAY}

        employee = contract.employee_id
        user = employee.user_id
        if not user:
            return worked_days

        # 1. Paid Leaves (excludes permission leaves which have paid=False)
        paid_leaves = LeaveRequest.search([
            ('user_id', '=', user.id),
            ('state', '=', 'approved'),
            ('paid', '=', True),
            ('start_date', '<=', date_to),
            ('end_date', '>=', date_from),
        ])
        total_leave_days = 0.0
        half_day_leave_dates = set()
        for leave in paid_leaves:
            total_leave_days += leave.days_requested
            if leave.is_half_day and leave.start_date:
                half_day_leave_dates.add(leave.start_date)

        if total_leave_days:
            worked_days.append({
                'name': 'Paid Leave',
                'sequence': 10,
                'code': 'LEAVE',
                'number_of_days': total_leave_days,
                'number_of_hours': total_leave_days * 8,
                'contract_id': contract.id,
            })

        # 2. Public Holidays
        public_holidays = PublicHoliday.search([
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ])
        public_holiday_dates = {fields.Date.to_date(ph.date) for ph in public_holidays}

        if public_holiday_dates:
            worked_days.append({
                'name': 'Public Holiday',
                'sequence': 20,
                'code': 'PH',
                'number_of_days': len(public_holiday_dates),
                'number_of_hours': len(public_holiday_dates) * 8,
                'contract_id': contract.id,
            })

        # 3. Attendance — days with a paid half-day leave count as 0.5
        attendance_records = Attendance.search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', datetime.combine(date_from_dt, datetime.min.time()).replace(tzinfo=UTC)),
            ('check_in', '<=', datetime.combine(date_to_dt, datetime.max.time()).replace(tzinfo=UTC)),
        ])
        present_days_set = {att.check_in.astimezone(UTC).date() for att in attendance_records if att.check_in}

        if not present_days_set:
            number_of_days = 0.0
            number_of_hours = 0.0
        else:
            number_of_days = sum(
                0.5 if d in half_day_leave_dates else 1.0
                for d in present_days_set
            )
            number_of_hours = number_of_days * 8

        worked_days.append({
            'name': 'Present (Attendance)',
            'sequence': 30,
            'code': 'PRESENT',
            'number_of_days': number_of_days,
            'number_of_hours': number_of_hours,
            'contract_id': contract.id,
        })

        # 3b. Late Login Deduction (0.5 day per late check-in, Asia/Dubai time)
        _DUBAI_TZ = timezone('Asia/Dubai')
        late_login_count = 0
        for att in attendance_records:
            if not att.check_in:
                continue
            check_in_dubai = att.check_in.replace(tzinfo=UTC).astimezone(_DUBAI_TZ)
            deadline = check_in_dubai.replace(hour=8, minute=50, second=0, microsecond=0)
            if check_in_dubai <= deadline:
                continue
            date_worked = check_in_dubai.date()
            permissions = LeaveRequest.search([
                ('user_id', '=', user.id),
                ('state', '=', 'approved'),
                ('leave_type_id.is_permission', '=', True),
                ('start_date', '=', date_worked),
            ])
            permission_hours = sum(permissions.mapped('hours_requested'))
            extended_deadline = deadline + timedelta(hours=permission_hours)
            if check_in_dubai > extended_deadline:
                late_login_count += 1

        if late_login_count:
            late_deduct_days = late_login_count * 0.5
            worked_days.append({
                'name': 'Late Login Deduction',
                'sequence': 35,
                'code': 'LATE_DEDUCT',
                'number_of_days': late_deduct_days,
                'number_of_hours': late_deduct_days * 8,
                'contract_id': contract.id,
            })

        # 4. Sundays in Period
        worked_days.append({
            'name': 'Sundays',
            'sequence': 40,
            'code': 'SUNDAY',
            'number_of_days': len(sundays_set),
            'number_of_hours': len(sundays_set) * 8,
            'contract_id': contract.id,
        })

        # 5. Total (WORK100)
        worked_days.append({
            'name': 'Total Days in Period',
            'sequence': 99,
            'code': 'WORK100',
            'number_of_days': len(total_days_set),
            'number_of_hours': len(total_days_set) * 8,
            'contract_id': contract.id,
        })

        return worked_days

    def export_payslip_to_excel_kgrn_ca_llc(self):
        # Create a new Excel workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Payslip Batch")
        
        # Format for text and cells
        bold_format = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '0.00'})
        
        # Define columns for the sheet (11 columns in total)
        columns = [
            "EDR",  # First Column
            "Employee ID",  # Second Column
            "Bank Route Number",  # Third Column
            "Bank IBAN Number",  # Fourth Column
            "Date From",  # Fifth Column
            "Date To",  # Sixth Column
            "Number of Days",  # Seventh Column
            "Total Amount",  # Eighth Column
            "Empty",  # Ninth Column
            "0",  # Tenth Column
            "Employee Name"  # Eleventh Column
        ]
        
        # Write columns headers
        for col_num, column in enumerate(columns):
            worksheet.write(0, col_num, column, bold_format)
        
        row = 0  # Starting row for data
        
        # Loop over all payslips in the payslip batch
        for payslip in self.slip_ids:
            # Check if employee's contract is for company_id == 1
            if payslip.employee_id.contract_id.company_id.id == 1 and not payslip.employee_id.direct_bank:
                employee = payslip.employee_id

                # First Column - "EDR"
                worksheet.write(row, 0, "EDR")
                
                # Second Column - Employee ID (labour_number)
                worksheet.write(row, 1, employee.labour_number)
                
                # Third Column - Bank Route Number
                worksheet.write(row, 2, employee.bank_route_number)
                
                # Fourth Column - Bank IBAN Number
                worksheet.write(row, 3, employee.bank_iban_number)
                
                # Fifth Column - Date From
                worksheet.write(row, 4, str(payslip.date_from))
                
                # Sixth Column - Date To
                worksheet.write(row, 5, str(payslip.date_to))
                
                # Seventh Column - Number of Days
                days_between = (payslip.date_to - payslip.date_from).days + 1
                worksheet.write(row, 6, days_between)
                
                # Eighth Column - Sum of line amounts (total of payslip lines)
                total_amount = sum(line.total for line in payslip.line_ids)
                worksheet.write(row, 7, total_amount, number_format)
                
                # Ninth Column - Empty
                worksheet.write(row, 8, "")
                
                # Tenth Column - "0"
                worksheet.write(row, 9, 0)
                
                # Eleventh Column - Employee Name (in uppercase)
                worksheet.write(row, 10, employee.name.upper())
                
                row += 1  # Move to the next row
        
        # Close the workbook
        workbook.close()

        # Get the file content from the BytesIO stream
        file_content = output.getvalue()
        
        # Encode the file content in base64
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')

        # Create an attachment with the base64-encoded file content
        attachment = self.env['ir.attachment'].create({
            'name': 'KGRN_CA_LLC_Payslip.xlsx',
            'type': 'binary',
            'datas': encoded_file_content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        # Return the URL for downloading the file
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def export_payslip_to_excel_avere_llc(self):
        # Create a new Excel workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Payslip Batch")
        
        # Format for text and cells
        bold_format = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '0.00'})
        
        # Define columns for the sheet (11 columns in total)
        columns = [
            "EDR",  # First Column
            "Labour Name",  # Second Column
            "Bank Route Number",  # Third Column
            "Bank IBAN Number",  # Fourth Column
            "Date From",  # Fifth Column
            "Date To",  # Sixth Column
            "Number of Days",  # Seventh Column
            "Total Amount",  # Eighth Column
            "Empty",  # Ninth Column
            "0",  # Tenth Column
            "Employee Name",  # Eleventh Column
        ]
        
        # Write columns headers
        for col_num, column in enumerate(columns):
            worksheet.write(0, col_num, column, bold_format)
        
        row = 0  # Starting row for data (row 0 is for headers)
        
        # Loop over all payslips in the payslip batch
        for payslip in self.slip_ids:
            # Check if employee's contract is for company_id == 14 (Avere LLC specific)
            if payslip.employee_id.contract_id.company_id.id == 14 and not payslip.employee_id.direct_bank:
                employee = payslip.employee_id

                # First Column - "EDR"
                worksheet.write(row, 0, "EDR")
                
                # Second Column - Labour Name (Employee's full name)
                worksheet.write(row, 1, employee.labour_number)
                
                # Third Column - Bank Route Number
                worksheet.write(row, 2, employee.bank_route_number)
                
                # Fourth Column - Bank IBAN Number
                worksheet.write(row, 3, employee.bank_iban_number)
                
                # Fifth Column - Date From
                worksheet.write(row, 4, str(payslip.date_from))
                
                # Sixth Column - Date To
                worksheet.write(row, 5, str(payslip.date_to))
                
                # Seventh Column - Number of Days (difference between Date To and Date From)
                days_between = (payslip.date_to - payslip.date_from).days + 1
                worksheet.write(row, 6, days_between)
                
                # Eighth Column - Total amount (sum of all lines for the payslip)
                total_amount = sum(line.total for line in payslip.line_ids)
                worksheet.write(row, 7, total_amount, number_format)
                
                # Ninth Column - Empty (Leave it blank)
                worksheet.write(row, 8, "")
                
                # Tenth Column - 0
                worksheet.write(row, 9, 0)
                
                # Eleventh Column - Employee Name (Uppercase)
                worksheet.write(row, 10, employee.name.upper())
                
                row += 1  # Move to the next row
        
        # Close the workbook
        workbook.close()

        # Get the file content from the BytesIO stream
        file_content = output.getvalue()
        
        # Encode the file content in base64
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')

        # Create an attachment with the base64-encoded file content
        attachment = self.env['ir.attachment'].create({
            'name': 'Avere_LLC_Payslip.xlsx',
            'type': 'binary',
            'datas': encoded_file_content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        # Return the URL for downloading the file
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def export_payslip_to_excel_kgrn_ca_rak(self):
        # Create a new Excel workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Payslip Batch")
        
        # Format for text and cells
        bold_format = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '0.00'})
        
        # Define columns for the sheet (11 columns in total)
        columns = [
            "EDR",  # First Column
            "Labour Name",  # Second Column
            "Bank Route Number",  # Third Column
            "Bank IBAN Number",  # Fourth Column
            "Date From",  # Fifth Column
            "Date To",  # Sixth Column
            "Number of Days",  # Seventh Column
            "Total Amount",  # Eighth Column
            "Empty",  # Ninth Column
            "0",  # Tenth Column
            "Employee Name",  # Eleventh Column
        ]
        
        # Write columns headers
        for col_num, column in enumerate(columns):
            worksheet.write(0, col_num, column, bold_format)
        
        row = 0  # Starting row for data (row 0 is for headers)
        
        # Loop over all payslips in the payslip batch
        for payslip in self.slip_ids:
            if payslip.employee_id.contract_id.company_id.id == 9 and not payslip.employee_id.direct_bank:
                employee = payslip.employee_id

                # First Column - "EDR"
                worksheet.write(row, 0, "EDR")
                
                # Second Column - Labour Name (Employee's full name)
                worksheet.write(row, 1, employee.labour_number)
                
                # Third Column - Bank Route Number
                worksheet.write(row, 2, employee.bank_route_number)
                
                # Fourth Column - Bank IBAN Number
                worksheet.write(row, 3, employee.bank_iban_number)
                
                # Fifth Column - Date From
                worksheet.write(row, 4, str(payslip.date_from))
                
                # Sixth Column - Date To
                worksheet.write(row, 5, str(payslip.date_to))
                
                # Seventh Column - Number of Days (difference between Date To and Date From)
                days_between = (payslip.date_to - payslip.date_from).days + 1
                worksheet.write(row, 6, days_between)
                
                # Eighth Column - Total amount (sum of all lines for the payslip)
                total_amount = sum(line.total for line in payslip.line_ids)
                worksheet.write(row, 7, total_amount, number_format)
                
                # Ninth Column - Empty (Leave it blank)
                worksheet.write(row, 8, "")
                
                # Tenth Column - 0
                worksheet.write(row, 9, 0)
                
                # Eleventh Column - Employee Name (Uppercase)
                worksheet.write(row, 10, employee.name.upper())
                
                row += 1  # Move to the next row
        
        # Close the workbook
        workbook.close()

        # Get the file content from the BytesIO stream
        file_content = output.getvalue()
        
        # Encode the file content in base64
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')

        # Create an attachment with the base64-encoded file content
        attachment = self.env['ir.attachment'].create({
            'name': 'KGRN_RAK_Payslip.xlsx',
            'type': 'binary',
            'datas': encoded_file_content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        # Return the URL for downloading the file
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def export_payslip_to_excel_abstract(self):
        # Create a new Excel workbook and add a worksheet
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet("Payslip Batch")
        
        # Format for text and cells
        bold_format = workbook.add_format({'bold': True})
        number_format = workbook.add_format({'num_format': '0.00'})
        
        # Define columns for the sheet (11 columns in total)
        columns = [
            "EDR",  # First Column
            "Labour Name",  # Second Column
            "Bank Route Number",  # Third Column
            "Bank IBAN Number",  # Fourth Column
            "Date From",  # Fifth Column
            "Date To",  # Sixth Column
            "Number of Days",  # Seventh Column
            "Total Amount",  # Eighth Column
            "Empty",  # Ninth Column
            "0",  # Tenth Column
            "Employee Name",  # Eleventh Column
        ]
        
        # Write columns headers
        for col_num, column in enumerate(columns):
            worksheet.write(0, col_num, column, bold_format)
        
        row = 0  # Starting row for data (row 0 is for headers)
        
        # Loop over all payslips in the payslip batch
        for payslip in self.slip_ids:
            # Check if employee's contract is for company_id == 14 (Avere LLC specific)
            if payslip.employee_id.contract_id.company_id.id == 3 and not payslip.employee_id.direct_bank:
                employee = payslip.employee_id

                # First Column - "EDR"
                worksheet.write(row, 0, "EDR")
                
                # Second Column - Labour Name (Employee's full name)
                worksheet.write(row, 1, employee.labour_number)
                
                # Third Column - Bank Route Number
                worksheet.write(row, 2, employee.bank_route_number)
                
                # Fourth Column - Bank IBAN Number
                worksheet.write(row, 3, employee.bank_iban_number)
                
                # Fifth Column - Date From
                worksheet.write(row, 4, str(payslip.date_from))
                
                # Sixth Column - Date To
                worksheet.write(row, 5, str(payslip.date_to))
                
                # Seventh Column - Number of Days (difference between Date To and Date From)
                days_between = (payslip.date_to - payslip.date_from).days + 1
                worksheet.write(row, 6, days_between)
                
                # Eighth Column - Total amount (sum of all lines for the payslip)
                total_amount = sum(line.total for line in payslip.line_ids)
                worksheet.write(row, 7, total_amount, number_format)
                
                # Ninth Column - Empty (Leave it blank)
                worksheet.write(row, 8, "")
                
                # Tenth Column - 0
                worksheet.write(row, 9, 0)
                
                # Eleventh Column - Employee Name (Uppercase)
                worksheet.write(row, 10, employee.name.upper())
                
                row += 1  # Move to the next row
        
        # Close the workbook
        workbook.close()

        # Get the file content from the BytesIO stream
        file_content = output.getvalue()
        
        # Encode the file content in base64
        encoded_file_content = base64.b64encode(file_content).decode('utf-8')

        # Create an attachment with the base64-encoded file content
        attachment = self.env['ir.attachment'].create({
            'name': 'Abstract_Payslip.xlsx',
            'type': 'binary',
            'datas': encoded_file_content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })
        
        # Return the URL for downloading the file
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }
