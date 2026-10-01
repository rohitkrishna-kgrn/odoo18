import base64
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError

COUNTRY_LABELS = {'india': 'India', 'dubai': 'Dubai (UAE)'}

# (field on leave.balance.report, column heading)
REPORT_COLUMNS = [
    ('employee_name', 'Employee Name'),
    ('employee_code', 'Employee ID'),
    ('department_name', 'Department'),
    ('country_label', 'Country / Employee Category'),
    ('leave_type_name', 'Leave Type'),
    ('period_label', 'Leave Period'),
    ('annual_entitlement', 'Total Leave Entitlement'),
    ('accrued', 'Leave Accrued / Allocated'),
    ('availed', 'Leave Availed'),
    ('current_balance', 'Current Leave Balance'),
    ('pending', 'Leave Pending for Approval'),
]
NUMERIC_FIELDS = {'annual_entitlement', 'accrued', 'availed', 'current_balance', 'pending'}


class LeaveBalanceReportXlsxWizard(models.TransientModel):
    _name = 'leave.balance.report.xlsx.wizard'
    _description = 'Download Leave Balance Report (Excel)'

    country = fields.Selection([
        ('india', 'India'),
        ('dubai', 'Dubai (UAE)'),
        ('both', 'Dubai (UAE) & India'),
    ], string='Country', required=True, default='india')

    period_mode = fields.Selection([
        ('current', 'Current Leave Month'),
        ('custom', 'Custom Date Range'),
        ('all', 'All Leave Months'),
    ], string='Period', required=True, default='current')
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')

    employee_ids = fields.Many2many(
        'hr.employee', string='Employees',
        domain="[('user_id.country', 'in', ['india', 'dubai'] if country == 'both' else [country])]",
        help="Leave empty to include every employee in the selected country/countries.")
    department_ids = fields.Many2many(
        'hr.department', string='Departments',
        help="Leave empty to include every department.")
    leave_type_ids = fields.Many2many(
        'leave.type', string='Leave Types',
        domain="['|', ('country_scope', '=', False), "
                "('country_scope', 'in', ['india', 'dubai'] if country == 'both' else [country])]",
        help="Leave empty to include every leave type applicable to the selected country/countries.")

    file_data = fields.Binary(string='File', readonly=True, attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)

    @api.onchange('period_mode')
    def _onchange_period_mode(self):
        if self.period_mode != 'custom':
            self.date_from = False
            self.date_to = False

    @api.onchange('country')
    def _onchange_country(self):
        self.employee_ids = False
        self.leave_type_ids = False

    def _build_domain(self):
        self.ensure_one()
        domain = []
        if self.country != 'both':
            domain.append(('country', '=', self.country))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.leave_type_ids:
            domain.append(('leave_type_id', 'in', self.leave_type_ids.ids))
        if self.period_mode == 'current':
            domain.append(('is_current_period', '=', True))
        elif self.period_mode == 'custom':
            if not self.date_from or not self.date_to:
                raise UserError(_("Please set both From and To dates for a custom period."))
            if self.date_from > self.date_to:
                raise UserError(_("The From date must not be after the To date."))
            domain += [('period_date', '>=', self.date_from), ('period_date', '<=', self.date_to)]
        return domain

    def action_download(self):
        self.ensure_one()
        rows = self.env['leave.balance.report'].search(
            self._build_domain(), order='country, employee_name, leave_type_id, period_date desc')
        if not rows:
            raise UserError(_("No leave balance data matches the selected filters."))

        sheet_title = 'Dubai (UAE) & India' if self.country == 'both' \
            else COUNTRY_LABELS.get(self.country, self.country)

        output = io.BytesIO()
        import xlsxwriter
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        title_fmt = book.add_format({'bold': True, 'font_size': 14})
        note_fmt = book.add_format({'font_size': 9, 'font_color': '#666666'})
        head_fmt = book.add_format({
            'bold': True, 'bg_color': '#1a4f72', 'font_color': 'white',
            'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
        text_fmt = book.add_format({'border': 1})
        num_fmt = book.add_format({'border': 1, 'num_format': '#,##0.00'})

        sheet = book.add_worksheet(sheet_title[:31])
        sheet.write(0, 0, '%s Leave Balance Report' % sheet_title, title_fmt)
        sheet.write(1, 0,
                    'Generated %s — rejected leave requests are never counted in '
                    'Availed or Pending' % fields.Date.context_today(self),
                    note_fmt)

        header_row = 3
        for col, (_field, label) in enumerate(REPORT_COLUMNS):
            sheet.write(header_row, col, label, head_fmt)
        sheet.set_column(0, 1, 22)
        sheet.set_column(2, 5, 18)
        sheet.set_column(6, len(REPORT_COLUMNS) - 1, 16)
        sheet.set_row(header_row, 30)
        sheet.freeze_panes(header_row + 1, 0)

        # Columns that identify *who* a row belongs to. These repeat once per
        # employee/leave-type/period row in the underlying data, but printing
        # them on every line makes a long sheet hard to read - so blank them
        # out after the first row of each (country, employee) block. This
        # never touches leave_type/period/numeric columns, so each row's
        # Total Entitlement / Accrued / Availed / Pending / Current Balance
        # always stays correctly paired with its own leave type - only the
        # repeated identity text is suppressed, not the underlying data.
        IDENTITY_FIELDS = ('employee_name', 'employee_code', 'department_name', 'country_label')

        line = header_row + 1
        last_key = None
        for row in rows:
            key = (row.country, row.employee_id.id)
            is_new_employee = key != last_key
            last_key = key

            values = {
                'employee_name': row.employee_name or '',
                'employee_code': row.employee_code or '',
                'department_name': row.department_id.name or '',
                'country_label': COUNTRY_LABELS.get(row.country, row.country),
                'leave_type_name': row.leave_type_id.name or '',
                'period_label': row.period_label or '',
            }
            for col, (field_name, _label) in enumerate(REPORT_COLUMNS):
                if field_name in NUMERIC_FIELDS:
                    sheet.write_number(line, col, row[field_name], num_fmt)
                elif field_name in IDENTITY_FIELDS and not is_new_employee:
                    sheet.write(line, col, '', text_fmt)
                else:
                    sheet.write(line, col, values[field_name], text_fmt)
            line += 1

        book.close()
        output.seek(0)

        self.write({
            'file_data': base64.b64encode(output.read()),
            'file_name': 'leave-balance-%s-%s.xlsx' % (self.country, fields.Date.context_today(self)),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file_data/%s?download=true' % (
                self._name, self.id, self.file_name),
            'target': 'self',
        }
