# -*- coding: utf-8 -*-
import base64
import io
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# (field on the report, column heading, 'int' | 'money')
REPORT_COLUMNS = [
    ('leads_count',        'Leads Received',            'int'),
    ('discovery_sent',     'Discovery Forms Sent',      'int'),
    ('discovery_received', 'Discovery Forms Received',  'int'),
    ('proposals_sent',     'Proposals Sent',            'int'),
    ('proposals_signed',   'Proposals Signed / Closed', 'int'),
    ('invoices_raised',    'Invoices Raised',           'int'),
    ('invoiced_amount',    'Invoiced Amount',           'money'),
    ('payments_count',     'Payments Received',         'int'),
    ('amount_collected',   'Amount Collected',          'money'),
    ('outstanding_amount', 'Outstanding',               'money'),
]


class SalespersonPerformanceWizard(models.TransientModel):
    _name = 'crm.salesperson.performance.wizard'
    _description = 'Download Salesperson Performance Report'

    period = fields.Selection([
        ('this_week', 'This Week'),
        ('this_month', 'This Month'),
        ('last_month', 'Last Month'),
        ('this_year', 'This Year'),
        ('custom', 'Custom Dates'),
    ], string='Period', required=True, default='this_month')

    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)

    user_ids = fields.Many2many(
        'res.users', string='Sales Team',
        domain=[('sales_team', '=', True)],
        help="Only users with Sales Team ticked on their user form can be "
             "chosen here. Leave empty to include everyone who was active "
             "in the period.")

    include_detail = fields.Boolean(
        string='Include Daily Breakdown', default=True,
        help="Adds a second sheet with one row per salesperson per day, "
             "behind the summary totals.")

    file_data = fields.Binary(string='File', readonly=True, attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        start, end = self._period_bounds(res.get('period') or 'this_month')
        res.setdefault('date_from', start)
        res.setdefault('date_to', end)
        return res

    @api.model
    def _period_bounds(self, period, today=None):
        today = today or fields.Date.context_today(self)
        if period == 'this_week':
            start = today + relativedelta(weeks=-1, days=1, weekday=0)
            end = today + relativedelta(weekday=6)
        elif period == 'this_month':
            start = today + relativedelta(day=1)
            end = today + relativedelta(day=1, months=1, days=-1)
        elif period == 'last_month':
            start = today + relativedelta(day=1, months=-1)
            end = today + relativedelta(day=1, days=-1)
        elif period == 'this_year':
            start = date(today.year, 1, 1)
            end = date(today.year, 12, 31)
        else:
            return today + relativedelta(day=1), today
        return start, end

    @api.onchange('period')
    def _onchange_period(self):
        for wizard in self:
            if wizard.period and wizard.period != 'custom':
                wizard.date_from, wizard.date_to = self._period_bounds(wizard.period)

    def _read_rows(self):
        """Report rows for the chosen period, grouped per salesperson."""
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("The From date must not be after the To date."))
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.user_ids:
            domain.append(('user_id', 'in', self.user_ids.ids))
        return self.env['crm.salesperson.performance'].search(domain, order='user_id, date')

    def action_download(self):
        self.ensure_one()
        rows = self._read_rows()
        if not rows:
            raise UserError(_(
                "Nothing was recorded between %(start)s and %(end)s for the "
                "people selected, so there is no report to download.",
                start=self.date_from, end=self.date_to))

        # Totals per salesperson - this is the sheet people actually want.
        per_user = {}
        for row in rows:
            bucket = per_user.setdefault(row.user_id, dict.fromkeys(
                [name for name, _label, _kind in REPORT_COLUMNS], 0))
            for name, _label, _kind in REPORT_COLUMNS:
                bucket[name] += row[name]

        output = io.BytesIO()
        import xlsxwriter
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        title_fmt = book.add_format({'bold': True, 'font_size': 14})
        note_fmt = book.add_format({'font_size': 9, 'font_color': '#666666'})
        head_fmt = book.add_format({
            'bold': True, 'bg_color': '#1a4f72', 'font_color': 'white',
            'border': 1, 'text_wrap': True, 'valign': 'vcenter'})
        name_fmt = book.add_format({'border': 1})
        int_fmt = book.add_format({'border': 1, 'num_format': '#,##0'})
        money_fmt = book.add_format({'border': 1, 'num_format': '#,##0.00'})
        tot_name = book.add_format({'bold': True, 'border': 1, 'bg_color': '#eef2f5'})
        tot_int = book.add_format({'bold': True, 'border': 1, 'bg_color': '#eef2f5', 'num_format': '#,##0'})
        tot_money = book.add_format({'bold': True, 'border': 1, 'bg_color': '#eef2f5', 'num_format': '#,##0.00'})
        date_fmt = book.add_format({'border': 1, 'num_format': 'yyyy-mm-dd'})

        currency = self.env.company.currency_id.name or ''
        period_label = dict(self._fields['period'].selection).get(self.period, '')

        # ── Sheet 1: one line per salesperson ────────────────────────────
        sheet = book.add_worksheet('Summary')
        sheet.write(0, 0, 'Sales Performance by Salesperson', title_fmt)
        sheet.write(1, 0, '%s — %s to %s (amounts in %s)' % (
            period_label, self.date_from, self.date_to, currency), note_fmt)

        header_row = 3
        sheet.write(header_row, 0, 'Salesperson', head_fmt)
        for idx, (_name, label, _kind) in enumerate(REPORT_COLUMNS, start=1):
            sheet.write(header_row, idx, label, head_fmt)
        sheet.set_column(0, 0, 28)
        sheet.set_column(1, len(REPORT_COLUMNS), 16)
        sheet.set_row(header_row, 30)
        sheet.freeze_panes(header_row + 1, 1)

        line = header_row + 1
        for user in sorted(per_user, key=lambda u: (u.name or '').lower()):
            sheet.write(line, 0, user.name or _('Unassigned'), name_fmt)
            for idx, (name, _label, kind) in enumerate(REPORT_COLUMNS, start=1):
                sheet.write_number(line, idx, per_user[user][name],
                                   money_fmt if kind == 'money' else int_fmt)
            line += 1

        sheet.write(line, 0, 'Total', tot_name)
        for idx, (name, _label, kind) in enumerate(REPORT_COLUMNS, start=1):
            sheet.write_number(line, idx, sum(b[name] for b in per_user.values()),
                               tot_money if kind == 'money' else tot_int)

        # ── Sheet 2: the daily rows behind those totals ──────────────────
        if self.include_detail:
            detail = book.add_worksheet('Daily Detail')
            detail.write(0, 0, 'Salesperson', head_fmt)
            detail.write(0, 1, 'Date', head_fmt)
            for idx, (_name, label, _kind) in enumerate(REPORT_COLUMNS, start=2):
                detail.write(0, idx, label, head_fmt)
            detail.set_column(0, 0, 28)
            detail.set_column(1, 1, 12)
            detail.set_column(2, len(REPORT_COLUMNS) + 1, 16)
            detail.set_row(0, 30)
            detail.freeze_panes(1, 2)

            for line, row in enumerate(rows, start=1):
                detail.write(line, 0, row.user_id.name or _('Unassigned'), name_fmt)
                detail.write_datetime(line, 1, row.date, date_fmt)
                for idx, (name, _label, kind) in enumerate(REPORT_COLUMNS, start=2):
                    detail.write_number(line, idx, row[name],
                                        money_fmt if kind == 'money' else int_fmt)

        book.close()
        output.seek(0)

        self.write({
            'file_data': base64.b64encode(output.read()),
            'file_name': 'sales-performance-%s-to-%s.xlsx' % (self.date_from, self.date_to),
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file_data/%s?download=true' % (
                self._name, self.id, self.file_name),
            'target': 'self',
        }
