import base64
import io
import logging

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class MisPerformanceReportLog(models.Model):
    """Monthly Performance Scorecard run: one record per (period, generation),
    holding the generated xlsx (in Odoo, for audit) and who it was emailed to.
    Created by the ir.cron `_cron_generate_monthly_scorecard` on the 1st of
    every month for the prior month; recipients are the members of the
    "MIS HR" group (mis_report_kgrn.group_mis_hr) at generation time — no
    one else receives this email."""
    _name = 'mis.performance.report.log'
    _description = 'MIS Performance Scorecard — Monthly Report Log'
    _order = 'period_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    period_date = fields.Date(string='Period', required=True, readonly=True)
    period_label = fields.Char(string='Month', required=True, readonly=True)
    generated_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    line_count = fields.Integer(string='Team Members', readonly=True)
    report_file = fields.Binary(string='Scorecard (xlsx)', readonly=True, attachment=True)
    report_filename = fields.Char(readonly=True)
    recipient_ids = fields.Many2many('res.users', string='Sent To', readonly=True)
    email_sent = fields.Boolean(readonly=True)

    @api.depends('period_label')
    def _compute_name(self):
        for rec in self:
            rec.name = f"Performance Scorecard — {rec.period_label}" if rec.period_label \
                else 'Performance Scorecard'

    @api.model
    def _cron_generate_monthly_scorecard(self):
        """Called monthly by ir.cron; generates the scorecard for the
        previous calendar month (e.g. runs Sep 1 → covers August)."""
        today = fields.Date.context_today(self)
        period_date = today.replace(day=1) - relativedelta(months=1)
        self._generate_scorecard(period_date)

    @api.model
    def _generate_scorecard(self, period_date):
        """Build the xlsx for `period_date` (any date within the target
        month), save it as a log record, and email it to MIS HR members
        only."""
        performance_lines = self.env['mis.performance.line'].sudo().search(
            [('period_date', '=', period_date.replace(day=1))],
            order='department_id, employee_name',
        )
        period_label = period_date.strftime('%b %Y')

        rows = []
        for line in performance_lines:
            rows.append({
                'department_id': line.department_id.name or 'Unassigned',
                'employee_name': line.employee_name,
                'performance_team': (line.performance_team or '').title(),
                'office_location': line.office_location,
                'period_label': line.period_label,
                'total_revenue': line.total_revenue,
                'invoices_raised_count': line.invoices_raised_count,
                'invoices_raised_amount': line.invoices_raised_amount,
                'payments_collected_amount': line.payments_collected_amount,
            })

        file_data = self._render_xlsx(period_label, rows)
        filename = f"Performance_Scorecard_{period_date.strftime('%Y_%m')}.xlsx"

        hr_group = self.env.ref('mis_report_kgrn.group_mis_hr', raise_if_not_found=False)
        recipients = hr_group.users.filtered(lambda u: u.active and u.email) if hr_group else self.env['res.users']

        log = self.create({
            'period_date': period_date.replace(day=1),
            'period_label': period_label,
            'line_count': len(rows),
            'report_file': file_data,
            'report_filename': filename,
            'recipient_ids': [(6, 0, recipients.ids)],
        })

        if recipients:
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'datas': file_data,
                'res_model': 'mis.performance.report.log',
                'res_id': log.id,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            })
            template = self.env.ref(
                'mis_report_kgrn.mail_template_mis_performance_scorecard', raise_if_not_found=False)
            if template:
                mail_id = template.send_mail(
                    log.id,
                    force_send=True,
                    email_values={
                        'email_to': ','.join(recipients.mapped('email')),
                        'attachment_ids': [(6, 0, [attachment.id])],
                    },
                )
                mail = self.env['mail.mail'].sudo().browse(mail_id)
                log.email_sent = mail.state == 'sent'
                if mail.state != 'sent':
                    _logger.warning(
                        "MIS Performance scorecard %s: email delivery failed (state=%s): %s",
                        period_label, mail.state, mail.failure_reason or '')
            else:
                _logger.warning(
                    "MIS Performance scorecard mail template missing; skipped email for %s", period_label)
        else:
            _logger.info(
                "MIS Performance scorecard %s: no MIS HR recipients configured, saved in Odoo only.", period_label)

        return log

    def _render_xlsx(self, period_label, rows):
        """One sheet, grouped by department: a shaded department header row,
        that department's employees underneath, a subtotal row, then the
        next department — ending in a grand total row."""
        import xlsxwriter

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(f'Scorecard {period_label}'[:31])

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#714B67', 'font_color': '#ffffff',
            'border': 1, 'valign': 'vcenter', 'text_wrap': True,
        })
        fmt_dept = workbook.add_format({
            'bold': True, 'bg_color': '#d9d2e9', 'border': 1, 'valign': 'vcenter',
        })
        fmt_text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_num = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0.00'})
        fmt_int = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0'})
        fmt_subtotal_label = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#f3f0f7'})
        fmt_subtotal_num = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#f3f0f7', 'num_format': '#,##0.00',
        })
        fmt_total_label = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#e9ecef'})
        fmt_total_num = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#e9ecef', 'num_format': '#,##0.00',
        })

        headers = ['Employee', 'Team', 'Office', 'Month', 'Value of Work Completed',
                   'Invoices Raised (No.)', 'Invoices Raised (AED)', 'Payments Collected (AED)']
        widths = [24, 12, 10, 10, 22, 18, 18, 20]
        for c, (label, width) in enumerate(zip(headers, widths)):
            sheet.write(0, c, label, fmt_header)
            sheet.set_column(c, c, width)
        sheet.freeze_panes(1, 0)

        grouped = {}
        for row in rows:
            grouped.setdefault(row['department_id'], []).append(row)

        agg_keys = ('total_revenue', 'invoices_raised_count',
                    'invoices_raised_amount', 'payments_collected_amount')
        grand_totals = {k: 0 for k in agg_keys}
        r = 1

        for dept_name, dept_rows in grouped.items():
            sheet.merge_range(r, 0, r, len(headers) - 1, dept_name, fmt_dept)
            r += 1
            dept_totals = {k: 0 for k in agg_keys}
            for row in dept_rows:
                sheet.write(r, 0, row['employee_name'], fmt_text)
                sheet.write(r, 1, row['performance_team'], fmt_text)
                sheet.write(r, 2, row['office_location'], fmt_text)
                sheet.write(r, 3, row['period_label'], fmt_text)
                sheet.write_number(r, 4, row['total_revenue'] or 0, fmt_num)
                sheet.write_number(r, 5, row['invoices_raised_count'] or 0, fmt_int)
                sheet.write_number(r, 6, row['invoices_raised_amount'] or 0, fmt_num)
                sheet.write_number(r, 7, row['payments_collected_amount'] or 0, fmt_num)
                for key in agg_keys:
                    dept_totals[key] += row[key] or 0
                r += 1

            sheet.write(r, 0, f'{dept_name} Subtotal', fmt_subtotal_label)
            sheet.write(r, 1, '', fmt_subtotal_label)
            sheet.write(r, 2, '', fmt_subtotal_label)
            sheet.write(r, 3, '', fmt_subtotal_label)
            sheet.write_number(r, 4, dept_totals['total_revenue'], fmt_subtotal_num)
            sheet.write_number(r, 5, dept_totals['invoices_raised_count'], fmt_subtotal_num)
            sheet.write_number(r, 6, dept_totals['invoices_raised_amount'], fmt_subtotal_num)
            sheet.write_number(r, 7, dept_totals['payments_collected_amount'], fmt_subtotal_num)
            r += 1
            for key in agg_keys:
                grand_totals[key] += dept_totals[key]

        sheet.write(r, 0, 'Grand Total', fmt_total_label)
        sheet.write(r, 1, '', fmt_total_label)
        sheet.write(r, 2, '', fmt_total_label)
        sheet.write(r, 3, '', fmt_total_label)
        sheet.write_number(r, 4, grand_totals['total_revenue'], fmt_total_num)
        sheet.write_number(r, 5, grand_totals['invoices_raised_count'], fmt_total_num)
        sheet.write_number(r, 6, grand_totals['invoices_raised_amount'], fmt_total_num)
        sheet.write_number(r, 7, grand_totals['payments_collected_amount'], fmt_total_num)
        r += 1

        sheet.autofilter(0, 0, r - 1, len(headers) - 1)

        workbook.close()
        output.seek(0)
        return base64.b64encode(output.read())
