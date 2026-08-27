import base64
import io
import logging

from odoo import models, fields, api
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

_TH = "padding:6px 8px;text-align:left;border:1px solid #ccc;vertical-align:top;"
_TD = "padding:6px 8px;border:1px solid #ccc;vertical-align:top;word-wrap:break-word;"

# Most-overdue-first. 0_30/not_due are listed for completeness even though
# the >30-day report domain means they'll never actually have lines.
BUCKET_ORDER = [
    ('90_plus', '90+ Days'),
    ('61_90', '61-90 Days'),
    ('31_60', '31-60 Days'),
    ('0_30', '0-30 Days'),
    ('not_due', 'Not Due'),
]


class WeeklyOverdueInvoiceReportLog(models.Model):
    """One record per Monday run: an immutable snapshot of every invoice that
    was >30 days overdue at generation time. Two separate emails go out from
    this same run: the full list to the recipient group ("Weekly Overdue
    Invoice Report Recipient" —
    weekly_overdue_invoice_report_gk.group_weekly_overdue_invoice_report_recipient
    — no one else receives this one; department heads and other stakeholders
    are added by ticking that access box on their user form, not hardcoded
    here), and individually to each PM with just their own invoices — gated
    by a second, separate access box ("Weekly Overdue Invoice Report -
    Project Manager" — group_weekly_overdue_invoice_report_pm) on the PM's
    own user form, so being a project's user_id alone never starts an
    email on its own."""
    _name = 'weekly.overdue.invoice.report.log'
    _description = 'Weekly Overdue Invoice Report — Sent Log'
    _order = 'generated_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    generated_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    invoice_count = fields.Integer(readonly=True)
    missing_reason_count = fields.Integer(readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    total_amount_due = fields.Monetary(readonly=True, currency_field='currency_id')
    recipient_ids = fields.Many2many('res.users', readonly=True, string='Sent To')
    email_sent = fields.Boolean(readonly=True)
    pm_report_count = fields.Integer(
        readonly=True, string='PM Emails Sent',
        help="Number of individual PMs who were separately emailed their own "
             "list of overdue invoices this run.")
    report_file = fields.Binary(string='Report (xlsx)', readonly=True, attachment=True)
    report_filename = fields.Char(readonly=True)
    report_pdf = fields.Binary(string='Report (pdf)', readonly=True, attachment=True)
    report_pdf_filename = fields.Char(readonly=True)
    line_ids = fields.One2many(
        'weekly.overdue.invoice.report.line', 'report_id', readonly=True)

    @api.depends('generated_date')
    def _compute_name(self):
        for rec in self:
            rec.name = "Overdue Invoice Report — %s" % (
                rec.generated_date.strftime('%d %b %Y') if rec.generated_date
                else 'Draft'
            )

    @api.model
    def _report_domain(self):
        return [
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('invoice_age_days', '>', 30),
            ('currency_id.name', '=', 'AED'),
            ('overdue_report_excluded', '=', False),
        ]

    @api.model
    def _cron_generate_weekly_report(self):
        """Called every Monday morning by ir.cron (see data/ir_cron.xml). Sends
        two kinds of email in the same run: the full list to the recipient
        group, and — separately — each PM their own personal list of just
        their invoices."""
        moves = self.env['account.move'].sudo().search(
            self._report_domain(), order='invoice_age_days desc')
        aed = self.env.ref('base.AED', raise_if_not_found=False)

        line_vals = []
        missing = 0
        total = 0.0
        for move in moves:
            if not move.why_not_collected:
                missing += 1
            total += move.amount_residual
            line_vals.append((0, 0, {
                'move_id': move.id,
                'invoice_number': move.name,
                'partner_name': move.partner_id.display_name,
                'team_name': move.engagement_team_id.name or '',
                'pm_name': move.engagement_pm_id.name or '',
                'ar_responsible_name': move.ar_responsible_id.name or '',
                'aging_bucket': move.aging_bucket,
                'days_overdue': move.invoice_age_days,
                'amount_due': move.amount_residual,
                'currency_id': move.currency_id.id,
                'last_followup_date': move.last_followup_date,
                'last_followup_method': move.last_followup_method,
                'last_followup_response': move.last_followup_response or '',
                'followup_count': move.followup_count,
                'followup_history': move._followup_history_text(),
                'why_not_collected': move.why_not_collected or '',
            }))

        group = self.env.ref(
            'weekly_overdue_invoice_report_gk.group_weekly_overdue_invoice_report_recipient',
            raise_if_not_found=False)
        # res.groups.users silently drops inactive res.users from the read,
        # even under sudo() — active_test=False is required to see them.
        # Many real staff here (e.g. Gopu's own account) are inactive Odoo
        # logins but still legitimate report recipients by email, so ticking
        # their access box must not silently fail to include them.
        recipients = group.sudo().with_context(active_test=False).users.filtered(lambda u: u.email) if group \
            else self.env['res.users']

        log = self.create({
            'invoice_count': len(moves),
            'missing_reason_count': missing,
            'total_amount_due': total,
            'currency_id': aed.id if aed else False,
            'recipient_ids': [(6, 0, recipients.ids)],
            'line_ids': line_vals,
            'pm_report_count': 0,
        })
        log.pm_report_count = log._send_pm_reports(moves)

        date_tag = log.generated_date.strftime('%Y_%m_%d')
        xlsx_filename = "Overdue_Invoice_Report_%s.xlsx" % date_tag
        xlsx_data = log._render_xlsx()
        pdf_filename = "Overdue_Invoice_Report_%s.pdf" % date_tag
        pdf_data = log._render_pdf()
        log.write({
            'report_file': xlsx_data, 'report_filename': xlsx_filename,
            'report_pdf': pdf_data, 'report_pdf_filename': pdf_filename,
        })

        if not recipients:
            _logger.info(
                "Weekly Overdue Invoice Report: no recipients configured (the "
                "recipient access box isn't ticked for anyone); report %s saved "
                "in Odoo only, no email sent.", log.name)
            return log

        attachment_vals = [{
            'name': xlsx_filename,
            'datas': xlsx_data,
            'res_model': 'weekly.overdue.invoice.report.log',
            'res_id': log.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        }]
        if pdf_data:
            attachment_vals.append({
                'name': pdf_filename,
                'datas': pdf_data,
                'res_model': 'weekly.overdue.invoice.report.log',
                'res_id': log.id,
                'mimetype': 'application/pdf',
            })
        attachments = self.env['ir.attachment'].create(attachment_vals)
        mail = self.env['mail.mail'].sudo().create({
            'subject': "Weekly Overdue Invoice Report — %s" % log.generated_date.strftime('%d %b %Y'),
            'body_html': log._render_report_summary_html(),
            'email_to': ','.join(recipients.mapped('email')),
            'attachment_ids': [(6, 0, attachments.ids)],
            'auto_delete': False,
        })
        mail.send()
        log.email_sent = mail.state == 'sent'
        if mail.state != 'sent':
            _logger.warning(
                "Weekly Overdue Invoice Report %s: email delivery failed (state=%s): %s",
                log.name, mail.state, mail.failure_reason or '')
        return log

    def _render_report_summary_html(self):
        self.ensure_one()
        return f"""
            <div style="font-family: Arial, sans-serif; font-size: 13px; color: #333;">
                <p>Dear Team,</p>
                <p>
                    Please find attached (Excel and PDF) the list of invoices
                    more than 30 days
                    overdue as of {self.generated_date.strftime('%d %b %Y')}
                    ({self.invoice_count} invoice(s), AED {self.total_amount_due:,.2f}
                    outstanding{f", {self.missing_reason_count} still missing a "
                    "'Why Not Collected' reason" if self.missing_reason_count else ""}).
                </p>
                <p>This report is generated automatically every Monday morning.</p>
                <p>Regards,<br/>Weekly Overdue Invoice Report (Automated)</p>
            </div>
        """

    def _company_logo_data_uri(self):
        """Odoo stores/serves res.company.logo as WebP on this instance, but
        wkhtmltopdf's rendering engine (0.12.x) can't decode WebP — the <img>
        just renders blank. Re-encode to PNG in memory before embedding so
        the logo actually shows up in the PDF.

        PIL's WebP plugin also isn't auto-registered inside Odoo's own
        process (Image.open() raises UnidentifiedImageError on genuinely
        valid WebP bytes unless PIL.WebPImagePlugin is explicitly imported
        first — Odoo apparently avoids importing it itself). Confirmed via
        direct testing in an `odoo-bin shell` session; the explicit import
        below is required, not just defensive."""
        logo = self.env.company.logo
        if not logo:
            return ''
        try:
            from PIL import Image, WebPImagePlugin  # noqa: F401 (import registers the WebP plugin)
            img = Image.open(io.BytesIO(base64.b64decode(logo)))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return 'data:image/png;base64,%s' % base64.b64encode(buf.getvalue()).decode()
        except Exception:
            _logger.exception("Weekly Overdue Invoice Report: could not re-encode company logo for PDF")
            return ''

    def _lines_grouped_by_bucket(self):
        """[(label, lines)] for each bucket that actually has lines, in
        BUCKET_ORDER (most overdue first) — used by both the PDF and xlsx so
        rows are sectioned by aging bucket instead of one flat table."""
        self.ensure_one()
        result = []
        for key, label in BUCKET_ORDER:
            lines = self.line_ids.filtered(lambda l, k=key: l.aging_bucket == k)
            if lines:
                result.append((label, lines))
        return result

    def _render_xlsx(self):
        self.ensure_one()
        import xlsxwriter

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Overdue Invoices'[:31])

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#F15D22', 'font_color': '#ffffff', 'font_name': 'Georgia',
            'border': 1, 'valign': 'vcenter', 'text_wrap': True,
        })
        fmt_text = workbook.add_format({'border': 1, 'valign': 'top', 'text_wrap': True, 'font_name': 'Calibri'})
        fmt_num = workbook.add_format({
            'border': 1, 'valign': 'top', 'num_format': '#,##0.00', 'font_name': 'Calibri'})
        fmt_int = workbook.add_format({
            'border': 1, 'valign': 'top', 'num_format': '#,##0', 'font_name': 'Calibri'})
        fmt_date = workbook.add_format({
            'border': 1, 'valign': 'top', 'num_format': 'dd mmm yyyy', 'font_name': 'Calibri'})
        fmt_missing = workbook.add_format({
            'border': 1, 'valign': 'top', 'font_color': '#a94442', 'bold': True,
            'text_wrap': True, 'font_name': 'Calibri',
        })
        fmt_bucket = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#FDEDE4', 'font_color': '#C74516',
            'font_size': 11, 'font_name': 'Georgia',
        })
        fmt_subtotal_label = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#FBD9C4', 'font_name': 'Calibri'})
        fmt_subtotal_num = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#FBD9C4', 'num_format': '#,##0.00', 'font_name': 'Calibri',
        })
        fmt_total_label = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#F15D22', 'font_color': '#ffffff', 'font_name': 'Calibri'})
        fmt_total_num = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#F15D22', 'font_color': '#ffffff',
            'num_format': '#,##0.00', 'font_name': 'Calibri',
        })

        headers = ['Invoice', 'Client', 'Team', 'PM', 'AR Responsible', 'Days Overdue',
                   'Amount Due (AED)', 'Last Follow-up', 'Why Not Collected']
        widths = [16, 28, 16, 18, 18, 12, 16, 14, 45]
        for c, (label, width) in enumerate(zip(headers, widths)):
            sheet.write(0, c, label, fmt_header)
            sheet.set_column(c, c, width)
        sheet.freeze_panes(1, 0)

        r = 1
        for bucket_label, lines in self._lines_grouped_by_bucket():
            sheet.merge_range(r, 0, r, len(headers) - 1, "%s (%d)" % (bucket_label, len(lines)), fmt_bucket)
            r += 1
            bucket_total = 0.0
            for line in lines:
                sheet.write(r, 0, line.invoice_number or '', fmt_text)
                sheet.write(r, 1, line.partner_name or '', fmt_text)
                sheet.write(r, 2, line.team_name or '', fmt_text)
                sheet.write(r, 3, line.pm_name or '', fmt_text)
                sheet.write(r, 4, line.ar_responsible_name or '', fmt_text)
                sheet.write_number(r, 5, line.days_overdue or 0, fmt_int)
                sheet.write_number(r, 6, line.amount_due or 0, fmt_num)
                if line.last_followup_date:
                    sheet.write_datetime(r, 7, line.last_followup_date, fmt_date)
                else:
                    sheet.write(r, 7, '—', fmt_text)
                if line.why_not_collected:
                    sheet.write(r, 8, line.why_not_collected, fmt_text)
                else:
                    sheet.write(r, 8, 'AR Responsible: Not Mentioned', fmt_missing)
                bucket_total += line.amount_due or 0
                r += 1

            sheet.write(r, 0, '%s Subtotal' % bucket_label, fmt_subtotal_label)
            for c in range(1, 5):
                sheet.write(r, c, '', fmt_subtotal_label)
            sheet.write(r, 5, '', fmt_subtotal_label)
            sheet.write_number(r, 6, bucket_total, fmt_subtotal_num)
            sheet.write(r, 7, '', fmt_subtotal_label)
            sheet.write(r, 8, '', fmt_subtotal_label)
            r += 1

        sheet.write(r, 0, 'Grand Total', fmt_total_label)
        for c in range(1, 5):
            sheet.write(r, c, '', fmt_total_label)
        sheet.write(r, 5, '', fmt_total_label)
        sheet.write_number(r, 6, self.total_amount_due, fmt_total_num)
        sheet.write(r, 7, '', fmt_total_label)
        sheet.write(r, 8, '', fmt_total_label)

        sheet.autofilter(0, 0, r - 1, len(headers) - 1)

        workbook.close()
        output.seek(0)
        return base64.b64encode(output.read())

    def _render_pdf(self):
        """Same invoice list as the xlsx, as a PDF via the module's own qweb
        report (weekly_overdue_invoice_report_gk.action_report_weekly_overdue_invoice).
        Returns base64 content, or False if rendering fails — a broken PDF
        should never block the xlsx/email from going out."""
        self.ensure_one()
        try:
            content, _report_type = self.env['ir.actions.report'] \
                ._render_qweb_pdf('weekly_overdue_invoice_report_gk.action_report_weekly_overdue_invoice', self.ids)
            return base64.b64encode(content)
        except Exception:
            _logger.exception(
                "Weekly Overdue Invoice Report %s: PDF rendering failed, "
                "continuing with the xlsx attachment only.", self.name)
            return False

    def _send_pm_reports(self, moves):
        """One email per Project Manager, scoped to just their own invoices
        that are >30 days overdue — sent the same Monday morning run as the
        group report. Which invoices are "theirs" is still identified the
        same way (Sale Order Line -> project -> Project
        Manager, i.e. engagement_pm_id) — but that alone doesn't get anyone
        an email: the PM must also have the "Weekly Overdue Invoice Report -
        Project Manager" access box ticked on their user form. Being a
        project's user_id is not, by itself, consent to receive this email.
        Returns how many PMs were emailed."""
        self.ensure_one()
        pm_group = self.env.ref(
            'weekly_overdue_invoice_report_gk.group_weekly_overdue_invoice_report_pm',
            raise_if_not_found=False)
        # active_test=False: res.groups.users silently drops inactive
        # res.users even under sudo(), and several real PMs in this database
        # (e.g. Md. Salman Rain) are inactive Odoo logins but still
        # legitimate recipients by email.
        eligible_pm_ids = set(
            pm_group.sudo().with_context(active_test=False).users.ids) if pm_group else set()

        by_pm = {}
        for move in moves:
            pm = move.engagement_pm_id
            if not pm or not pm.email or pm.id not in eligible_pm_ids:
                continue
            by_pm.setdefault(pm, self.env['account.move'])
            by_pm[pm] |= move

        for pm, pm_moves in by_pm.items():
            mail = self.env['mail.mail'].sudo().create({
                'subject': "Your Overdue Invoices (>30 Days) — %s" % self.generated_date.strftime('%d %b %Y'),
                'body_html': self._render_pm_report_html(pm, pm_moves),
                'email_to': pm.email,
                'auto_delete': True,
            })
            mail.send()
            if mail.state != 'sent':
                _logger.warning(
                    "Weekly Overdue Invoice Report %s: PM email to %s failed "
                    "(state=%s): %s", self.name, pm.email, mail.state, mail.failure_reason or '')
        return len(by_pm)

    def _render_pm_report_html(self, pm, moves):
        rows = []
        total = 0.0
        for move in moves:
            total += move.amount_residual
            reason = html_escape(move.why_not_collected) if move.why_not_collected \
                else '<span style="color:#a94442;font-weight:bold;">AR Responsible: Not Mentioned</span>'
            rows.append(
                "<tr>"
                f"<td style='{_TD}'>{html_escape(move.name or '')}</td>"
                f"<td style='{_TD}'>{html_escape(move.partner_id.display_name or '')}</td>"
                f"<td style='{_TD};text-align:right'>{move.invoice_age_days}</td>"
                f"<td style='{_TD};text-align:right'>{move.amount_residual:,.2f}</td>"
                f"<td style='{_TD}'>{move.last_followup_date or '—'}</td>"
                f"<td style='{_TD}'>{reason}</td>"
                "</tr>"
            )
        return f"""
            <div style="font-family: Arial, sans-serif; font-size: 12px; color: #333;">
                <p>Dear {html_escape(pm.name or '')},</p>
                <p>
                    Here are your invoices more than 30 days overdue as of
                    {self.generated_date.strftime('%d %b %Y')}
                    ({len(moves)} invoice(s), AED {total:,.2f} outstanding).
                </p>
                <table style="border-collapse: collapse; width: 100%; table-layout: fixed;" border="1">
                    <colgroup>
                        <col style="width:14%"/><col style="width:22%"/><col style="width:14%"/>
                        <col style="width:16%"/><col style="width:14%"/><col style="width:20%"/>
                    </colgroup>
                    <tr style="background:#f3f0f7;">
                        <th style="{_TH}">Invoice</th><th style="{_TH}">Client</th>
                        <th style="{_TH};text-align:right">Days Overdue</th>
                        <th style="{_TH};text-align:right">Amount Due (AED)</th>
                        <th style="{_TH}">Last Follow-up</th>
                        <th style="{_TH}">Why Not Collected</th>
                    </tr>
                    {''.join(rows)}
                </table>
                <p>This report is generated automatically every Monday morning.</p>
                <p>Regards,<br/>Weekly Overdue Invoice Report (Automated)</p>
            </div>
        """


class WeeklyOverdueInvoiceReportLine(models.Model):
    _name = 'weekly.overdue.invoice.report.line'
    _description = 'Weekly Overdue Invoice Report — Line Snapshot'
    _order = 'days_overdue desc'

    report_id = fields.Many2one(
        'weekly.overdue.invoice.report.log', required=True, ondelete='cascade', index=True)
    move_id = fields.Many2one('account.move', string='Invoice', ondelete='set null')
    invoice_number = fields.Char(string='Invoice Number')
    partner_name = fields.Char(string='Client')
    team_name = fields.Char(string='Team')
    pm_name = fields.Char(string='PM')
    ar_responsible_name = fields.Char(string='AR Responsible')
    aging_bucket = fields.Selection(
        [
            ('not_due', 'Not Due'),
            ('0_30', '0-30 Days'),
            ('31_60', '31-60 Days'),
            ('61_90', '61-90 Days'),
            ('90_plus', '90+ Days'),
        ],
        string='Aging Bucket',
        help="Snapshotted from the invoice's own Aging Bucket at report "
             "generation time — used to section the PDF/xlsx by bucket.",
    )
    days_overdue = fields.Integer(string='Days Overdue')
    currency_id = fields.Many2one('res.currency')
    amount_due = fields.Monetary(string='Amount Due', currency_field='currency_id')
    last_followup_date = fields.Date(string='Last Follow-up Date')
    # The follow-up log as it stood at generation time. Snapshotted, not
    # related through move_id: this report is evidence of what was known on
    # the Monday it went out, and later chasing must not rewrite it.
    last_followup_method = fields.Selection(
        [
            ('email', 'Email'),
            ('call', 'Call'),
            ('whatsapp', 'WhatsApp'),
        ],
        string='Last Follow-up Method',
    )
    last_followup_response = fields.Text(string='Last Client Response')
    followup_count = fields.Integer(string='Follow-ups')
    followup_history = fields.Text(
        string='Follow-up History',
        help="Every follow-up logged on the invoice at generation time, "
             "oldest first.")
    why_not_collected = fields.Text(string='Why Not Collected')
