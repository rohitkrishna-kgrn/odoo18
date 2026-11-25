import base64
import io
from collections import OrderedDict

from odoo.tools.misc import file_open

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..models import tools


class PayrollCountryReportWizard(models.TransientModel):
    _name = 'payroll.country.report.wizard'
    _description = 'Country Payroll Report'

    payroll_country_id = fields.Many2one('payroll.country', string='Country', required=True)
    country_id = fields.Many2one(related='payroll_country_id.country_id', string='Country Record')
    company_ids = fields.Many2many('res.company', string='Companies',
                                   help="Pre-filled with the companies of the payroll batch(es); remove any you "
                                        "do not want. Empty = every company you can see.")
    allowed_company_ids = fields.Many2many('res.company', compute='_compute_allowed_company_ids')
    month = fields.Selection(tools.MONTHS, string='Month', required=True)
    year = fields.Selection(tools.YEARS, string='Year', required=True)
    batch_id = fields.Many2one('payroll.country.batch', string='Payroll Batch')
    include_draft = fields.Boolean(string='Include not yet approved batches', default=True)
    output = fields.Selection([('pdf', 'PDF'), ('xlsx', 'Excel')], default='pdf', required=True)
    file_data = fields.Binary(readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    @api.depends('payroll_country_id', 'batch_id', 'month', 'year')
    def _compute_allowed_company_ids(self):
        for wiz in self:
            companies = wiz.payroll_country_id._country_companies() if wiz.payroll_country_id else \
                self.env['res.company']
            wiz.allowed_company_ids = companies | wiz._batch_companies()

    def _batches(self):
        """The batch the report was opened from, else the live batches of the period."""
        self.ensure_one()
        if self.batch_id:
            return self.batch_id
        if not (self.payroll_country_id and self.month and self.year):
            return self.env['payroll.country.batch']
        return self.env['payroll.country.batch'].search([
            ('payroll_country_id', '=', self.payroll_country_id.id), ('month', '=', self.month),
            ('year', '=', self.year), ('state', '!=', 'cancel')])

    def _batch_companies(self):
        """Companies the batch(es) were run for, limited to those the user may read."""
        ids = self._batches().sudo().company_ids.ids
        return self.env['res.company'].search([('id', 'in', ids)]) if ids else self.env['res.company']

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        for wiz, vals in zip(wizards, vals_list):
            if 'company_ids' not in vals:
                wiz.company_ids = wiz._batch_companies()
        return wizards

    @api.onchange('payroll_country_id', 'month', 'year')
    def _onchange_period_companies(self):
        if not self.batch_id:
            self.company_ids = self._batch_companies()


    def _get_lines(self):
        """Saved payroll lines only - with the user's own record rules (officer:
        assigned countries; approver: own companies' submitted batches)."""
        self.ensure_one()
        domain = [('country_id', '=', self.country_id.id), ('month', '=', self.month),
                  ('year', '=', self.year), ('state', '!=', 'cancel')]
        if self.batch_id:
            domain.append(('batch_id', '=', self.batch_id.id))
        if self.company_ids:
            domain.append(('company_id', 'in', self.company_ids.ids))
        if not self.include_draft:
            domain.append(('batch_state', '=', 'approved'))
        return self.env['payroll.country.line'].search(domain, order='company_name, employee_name')

    def _report_groups(self):
        groups = OrderedDict()
        for line in self._get_lines():
            groups.setdefault(line.company_name or '', self.env['payroll.country.line'])
            groups[line.company_name or ''] |= line
        return groups

    def _kgrn_logo_data_uri(self):
        """KGRN logo for the PDF, embedded (wkhtmltopdf never has to fetch it)."""
        with file_open('om_hr_payroll_extended_gk/static/img/kgrn_logo.png', 'rb') as fh:
            return 'data:image/png;base64,%s' % base64.b64encode(fh.read()).decode()

    # ------------------------------------------------------------ PDF register layout
    def _register_columns(self, show_pf, show_wfh=False):
        """(group, key, label, digits, bold) of the PDF register, in print order."""
        cols = [
            ('att', 'working_days', 'Work Days', 1, False),
            ('att', 'present_days', 'Present', 1, False),
            ('att', 'absent_days', 'Absent', 1, False),
            ('att', 'paid_leave_days', 'Paid Leave', 1, False),
            ('att', 'unpaid_leave_days', 'Unpaid Leave', 1, False),
            ('att', 'lop_days', 'LOP Days', 2, False),
            ('earn', 'basic', 'Basic', 2, False),
            ('earn', 'hra', 'HRA', 2, False),
            ('earn', 'other_allowances', 'Other Allow.', 2, False),
            ('earn', 'ot_other', 'OT / Other', 2, False),
            ('earn', 'gross', 'Gross', 2, True),
        ]
        if show_pf:
            cols += [('ded', 'epf', 'EPF', 2, False), ('ded', 'esi', 'ESI', 2, False)]
        cols += [
            ('ded', 'lop_amount', 'LOP', 2, False),
            ('ded', 'other_deductions', 'Other', 2, False),
        ]
        if show_wfh:
            cols += [('ded', 'wfh_deduction', 'WFH', 2, False)]
        cols += [('ded', 'total_deductions', 'Total', 2, True)]
        return cols

    @api.model
    def _register_value(self, lines, key):
        """Sum of one register column over lines (one line = its value)."""
        if key == 'ot_other':
            return sum(lines.mapped('overtime_amount')) + sum(lines.mapped('other_earnings'))
        return sum(lines.mapped(key))

    @api.model
    def _fmt_num(self, value, digits=2):
        """Register number: thousands separators, a dash for zero."""
        value = round(value or 0.0, digits)
        if not value:
            return '\u2013'
        return '{:,.{d}f}'.format(value, d=digits)

    def _register_summary(self):
        lines = self._get_lines()
        return {
            'employees': len(lines),
            'companies': len(set(lines.mapped('company_name'))),
            'gross': sum(lines.mapped('gross')),
            'deductions': sum(lines.mapped('total_deductions')),
            'net': sum(lines.mapped('net')),
            'currency': lines[:1].currency_id.name or '',
        }

    def _title(self):
        return _("%(country)s Payroll - %(month)s %(year)s",
                 country=self.country_id.name, month=tools.month_label(self.month), year=self.year)

    def action_generate(self):
        self.ensure_one()
        if not self._get_lines():
            raise UserError(_("No saved payroll lines you can see match these filters."))
        if self.output == 'pdf':
            return self.env.ref('om_hr_payroll_extended_gk.action_report_payroll_register').report_action(self)
        return self._export_xlsx()

    COLUMNS = [
        ('employee_name', 'Employee Name'), ('employee_code', 'Employee ID'), ('company_name', 'Company'),
        ('department_name', 'Department'), ('job_name', 'Designation'),
        ('working_days', 'Working Days'), ('present_days', 'Present'), ('absent_days', 'Absent'),
        ('paid_leave_days', 'Paid Leave'), ('unpaid_leave_days', 'Unpaid Leave'), ('lop_days', 'LOP Days'),
        ('overtime_hours', 'OT Hours'),
        ('basic', 'Basic Salary'), ('hra', 'HRA'), ('other_allowances', 'Other Allowances'),
        ('overtime_amount', 'Overtime Pay'), ('other_earnings', 'Other Earnings'), ('gross', 'Gross Salary'),
        ('epf', 'EPF'), ('esi', 'ESI'), ('lop_amount', 'LOP Deduction'), ('other_deductions', 'Other Deductions'),
        ('wfh_deduction', 'Work From Home Deduction'), ('total_other_deductions', 'Total Other Deductions'),
        ('total_deductions', 'Total Deductions'), ('net', 'Net Salary'),
        ('bank_name', 'Bank'), ('bank_account_masked', 'Account No'), ('bank_iban_masked', 'IBAN'),
        ('state', 'Status'),
    ]
    MONEY = {'basic', 'hra', 'other_allowances', 'overtime_amount', 'other_earnings', 'gross', 'epf', 'esi',
             'lop_amount', 'other_deductions', 'wfh_deduction', 'total_other_deductions', 'total_deductions', 'net'}

    def _export_xlsx(self):
        import xlsxwriter
        buf = io.BytesIO()
        book = xlsxwriter.Workbook(buf, {'in_memory': True})
        sheet = book.add_worksheet(_('Payroll'))
        title = book.add_format({'bold': True, 'font_size': 14})
        head = book.add_format({'bold': True, 'bg_color': '#F25D23', 'font_color': '#FFFFFF', 'border': 1,
                                'text_wrap': True, 'valign': 'vcenter'})
        money = book.add_format({'num_format': '#,##0.00', 'border': 1})
        num = book.add_format({'num_format': '0.00', 'border': 1})
        text = book.add_format({'border': 1})
        total_money = book.add_format({'num_format': '#,##0.00', 'bold': True, 'top': 2})
        bold = book.add_format({'bold': True, 'top': 2})
        sheet.write(0, 0, self._title(), title)
        sheet.write(1, 0, _("Generated %s by %s") % (fields.Datetime.context_timestamp(self, fields.Datetime.now())
                                                     .strftime('%d %b %Y %H:%M'), self.env.user.name))
        row = 3
        lines = self._get_lines()
        columns = self.COLUMNS if any(lines.mapped('pf_esi_applies')) else \
            [c for c in self.COLUMNS if c[0] not in ('epf', 'esi')]      # PF / ESI: India only
        if not any(lines.mapped('wfh_deduction')):                       # Work From Home: when deducted
            columns = [c for c in columns if c[0] not in ('wfh_deduction', 'total_other_deductions')]
        for col, (_f, label) in enumerate(columns):
            sheet.write(row, col, label, head)
            sheet.set_column(col, col, 22 if col < 5 else 13)
        state_labels = dict(self.env['payroll.country.line']._fields['state'].selection)
        for line in lines:
            row += 1
            for col, (fname, _label) in enumerate(columns):
                value = line[fname]
                if fname == 'state':
                    sheet.write(row, col, state_labels.get(value, value), text)
                elif fname in self.MONEY:
                    sheet.write_number(row, col, value or 0.0, money)
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    sheet.write_number(row, col, value, num)
                else:
                    sheet.write(row, col, value or '', text)
        row += 1
        sheet.write(row, 0, _("Total (%s employees)") % len(lines), bold)
        for col, (fname, _label) in enumerate(columns):
            if fname in self.MONEY:
                sheet.write_number(row, col, sum(lines.mapped(fname)), total_money)
        sheet.freeze_panes(4, 1)
        book.close()
        name = '%s_Payroll_%s_%s.xlsx' % (self.country_id.code or 'XX', self.year, tools.month_label(self.month))
        self.write({'file_data': base64.b64encode(buf.getvalue()), 'file_name': name})
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=%s&id=%s&field=file_data&filename_field=file_name&download=true'
                   % (self._name, self.id),
            'target': 'self',
        }
