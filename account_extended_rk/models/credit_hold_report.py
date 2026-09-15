import base64
import io
from datetime import timedelta

import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError


def _days_overdue(move, as_of):
    """Days a customer invoice is past its due date, as of `as_of`.

    Recomputed here rather than read off the stored `invoice_age_days` --
    that field only refreshes on the daily AR aging cron, and this report has
    to be correct the moment it is generated, not as of last night.
    """
    if move.state != 'posted' or move.payment_state not in ('not_paid', 'partial'):
        return 0
    if not move.invoice_date_due:
        return 0
    due = fields.Date.to_date(move.invoice_date_due)
    return max(0, (as_of - due).days)


def _projects_for(env, partner, invoices):
    """Projects linked to this customer: via the sale orders behind the
    invoices, or directly by customer -- same two paths
    `res.partner._credit_hold_recipients` follows to find a PM to notify.
    """
    orders = invoices.invoice_line_ids.sale_line_ids.order_id
    domain = [('partner_id', 'child_of', partner.commercial_partner_id.id)]
    if orders:
        domain = ['|', ('sale_order_id', 'in', orders.ids)] + domain
    return env['project.project'].sudo().search(domain)


def _project_status(project):
    if not project.active:
        return _("Archived")
    return project.stage_id.name or _("No Stage")


def _project_reference(project):
    return project.sale_order_id.name or project.name


class CreditHoldReportWizardMixin(models.AbstractModel):
    _name = 'credit.hold.report.wizard.mixin'
    _description = 'Credit Hold Report Wizard Common Fields'

    partner_ids = fields.Many2many('res.partner', string='Customers')

    show_invoice_details = fields.Boolean(
        string='Invoice Details', default=True,
        help="Show the invoice table for each customer in the report. In an "
             "Excel download, this is the sheet of per-customer invoice rows.")
    show_project_details = fields.Boolean(
        string='Linked Projects', default=True,
        help="Show the linked-projects table for each customer in the report. "
             "In an Excel download, this is the sheet of per-customer projects.")

    download_pdf = fields.Boolean(string='PDF', default=True)
    download_excel = fields.Boolean(string='Excel', default=False)

    # Two binary slots, not one -- when both formats are picked, PDF and
    # Excel are downloaded as two separate files (not a zip), so each needs
    # its own /web/content column to be fetched from independently.
    file_data = fields.Binary(string='File', readonly=True, attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)
    file_data_2 = fields.Binary(string='File 2', readonly=True, attachment=False)
    file_name_2 = fields.Char(string='File Name 2', readonly=True)

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_download(self):
        """Single Download button behind both format checkboxes.

        PDF-only keeps the original UX (opens through the report controller
        rather than a forced download). Excel-only writes the xlsx onto this
        transient row and hands back a direct download URL. Both together
        writes both onto this row and returns a small client action
        (credit_hold_multi_download.js) that fires the two downloads one
        after another -- the user wants two individual files, not a zip.
        """
        self.ensure_one()
        if not self.download_pdf and not self.download_excel:
            raise UserError(_(
                "Select at least one format -- PDF, Excel, or both -- before "
                "downloading."))

        if self.download_pdf and not self.download_excel:
            return self.env.ref(self._report_xmlid).report_action(self)

        today = fields.Date.context_today(self)

        if self.download_pdf and self.download_excel:
            pdf_name = '%s_%s.pdf' % (self._export_basename, today)
            xlsx_name = '%s_%s.xlsx' % (self._export_basename, today)
            self.write({
                'file_data': base64.b64encode(self._render_pdf_bytes()),
                'file_name': pdf_name,
                'file_data_2': base64.b64encode(self._render_xlsx_bytes()),
                'file_name_2': xlsx_name,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'account_extended_rk.credit_hold_multi_download',
                'params': {
                    'urls': [
                        '/web/content/%s/%s/file_data/%s?download=true' % (
                            self._name, self.id, pdf_name),
                        '/web/content/%s/%s/file_data_2/%s?download=true' % (
                            self._name, self.id, xlsx_name),
                    ],
                },
            }

        name = '%s_%s.xlsx' % (self._export_basename, today)
        self.write({
            'file_data': base64.b64encode(self._render_xlsx_bytes()),
            'file_name': name,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file_data/%s?download=true' % (
                self._name, self.id, self.file_name),
            'target': 'self',
        }

    def _render_pdf_bytes(self):
        self.ensure_one()
        content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
            self._report_xmlid, res_ids=self.ids)
        return content

    def _render_xlsx_bytes(self):
        """Customers-only sheet always; Invoice Details / Linked Projects
        sheets only when their matching checkbox is on -- the same two
        checkboxes that gate those sections in the PDF.
        """
        self.ensure_one()
        report_data = self._get_report_data()
        customers = report_data['customers']

        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        head_fmt = book.add_format({
            'bold': True, 'bg_color': '#f25d23', 'font_color': 'white', 'border': 1})
        cell_fmt = book.add_format({'border': 1})
        date_fmt = book.add_format({'border': 1, 'num_format': 'dd-mm-yyyy'})
        money_fmt = book.add_format({'border': 1, 'num_format': '#,##0.00'})

        sheet = book.add_worksheet('Customers')
        sheet.write(0, 0, 'Customer', head_fmt)
        sheet.set_column(0, 0, 40)
        for row, cust in enumerate(customers, start=1):
            sheet.write(row, 0, cust['partner'].display_name or '', cell_fmt)

        if self.show_invoice_details:
            sheet = book.add_worksheet('Invoice Details')
            headers = ['Customer', 'Invoice', 'Invoice Date', 'Due Date',
                        'Days Overdue', 'State', 'Payment State', 'Amount Due']
            for col, label in enumerate(headers):
                sheet.write(0, col, label, head_fmt)
            sheet.set_column(0, 1, 26)
            sheet.set_column(2, 3, 14)
            sheet.set_column(4, 7, 16)
            row = 1
            for cust in customers:
                name = cust['partner'].display_name or ''
                for line in self._export_invoice_rows(cust):
                    move = line['move']
                    sheet.write(row, 0, name, cell_fmt)
                    sheet.write(row, 1, move.name or '', cell_fmt)
                    if move.invoice_date:
                        sheet.write_datetime(row, 2, move.invoice_date, date_fmt)
                    else:
                        sheet.write(row, 2, '', cell_fmt)
                    if move.invoice_date_due:
                        sheet.write_datetime(row, 3, move.invoice_date_due, date_fmt)
                    else:
                        sheet.write(row, 3, '', cell_fmt)
                    sheet.write_number(row, 4, line['days_overdue'], cell_fmt)
                    sheet.write(row, 5, line['state_label'], cell_fmt)
                    sheet.write(row, 6, line['payment_state_label'], cell_fmt)
                    sheet.write_number(row, 7, move.amount_residual, money_fmt)
                    row += 1

        if self.show_project_details:
            sheet = book.add_worksheet('Linked Projects')
            headers = ['Customer', 'Project', 'Reference', 'Status']
            for col, label in enumerate(headers):
                sheet.write(0, col, label, head_fmt)
            sheet.set_column(0, 2, 30)
            sheet.set_column(3, 3, 18)
            row = 1
            for cust in customers:
                name = cust['partner'].display_name or ''
                for prow in cust['projects']:
                    sheet.write(row, 0, name, cell_fmt)
                    sheet.write(row, 1, prow['project'].name or '', cell_fmt)
                    sheet.write(row, 2, prow['reference'] or '', cell_fmt)
                    sheet.write(row, 3, prow['status'] or '', cell_fmt)
                    row += 1

        book.close()
        output.seek(0)
        return output.read()

    def _customer_domain(self, field='partner_id'):
        """OR'd `child_of` domain across every selected customer, so a debt
        on a child contact still matches its parent -- same as everywhere
        else credit hold customers are looked up.
        """
        commercial_ids = self.partner_ids.mapped('commercial_partner_id').ids
        if not commercial_ids:
            return []
        domain = ['|'] * (len(commercial_ids) - 1)
        domain += [(field, 'child_of', cid) for cid in commercial_ids]
        return domain

    def _invoice_rows(self, invoices, as_of):
        rows = []
        for move in invoices.sorted('invoice_date_due'):
            rows.append({
                'move': move,
                'days_overdue': _days_overdue(move, as_of),
                'state_label': dict(move._fields['state'].selection).get(move.state, ''),
                'payment_state_label': dict(
                    move._fields['payment_state'].selection).get(move.payment_state, ''),
            })
        return rows

    def _project_rows(self, projects):
        return [{
            'project': project,
            'status': _project_status(project),
            'reference': _project_reference(project),
        } for project in projects]


class CreditHoldRemovedReportWizard(models.TransientModel):
    _name = 'credit.hold.removed.report.wizard'
    _inherit = 'credit.hold.report.wizard.mixin'
    _description = 'Credit Hold Removed Details Report Wizard'

    _report_xmlid = 'account_extended_rk.action_report_credit_hold_removed'
    _export_basename = 'Credit_Hold_Removed_Details'

    date_from = fields.Date(
        string='From Date', required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(
        string='To Date', required=True,
        default=lambda self: fields.Date.context_today(self))

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise UserError(_("From Date must be on or before To Date."))

    def _export_invoice_rows(self, cust):
        return [row for release in cust['releases'] for row in release['rows']]

    def _get_report_data(self):
        self.ensure_one()
        today = fields.Date.context_today(self)

        domain = [
            ('event_type', '=', 'release'),
            ('event_date', '>=', fields.Datetime.to_datetime(self.date_from)),
            ('event_date', '<', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)),
        ]
        domain += self._customer_domain()

        events = self.env['res.partner.credit.hold.event'].sudo().search(
            domain, order='partner_id, event_date')

        customers = []
        for partner in events.mapped('partner_id'):
            partner_events = events.filtered(lambda e, p=partner: e.partner_id == p)
            invoices = partner_events.mapped('invoice_ids')
            projects = _projects_for(self.env, partner, invoices)

            releases = []
            for event in partner_events.sorted('event_date'):
                override = event.override_id
                releases.append({
                    'event': event,
                    'removed_by': override.user_id.display_name if override else _(
                        "System (Invoices Settled)"),
                    'reason': override.reason if override else _(
                        "Outstanding invoices were fully settled or credited."),
                    'rows': self._invoice_rows(event.invoice_ids, today),
                })

            customers.append({
                'partner': partner,
                'releases': releases,
                'projects': self._project_rows(projects),
            })

        return {'customers': customers}


class CreditHoldCurrentReportWizard(models.TransientModel):
    _name = 'credit.hold.current.report.wizard'
    _inherit = 'credit.hold.report.wizard.mixin'
    _description = 'Overall Current Credit Hold Report Wizard'

    _report_xmlid = 'account_extended_rk.action_report_credit_hold_current'
    _export_basename = 'Overall_Current_Credit_Hold'

    as_of_date = fields.Date(
        string='As of Date', required=True, default=fields.Date.context_today)

    def _export_invoice_rows(self, cust):
        return cust['rows']

    def _current_hold_state(self):
        """{partner: {invoices, hold_date, amount, max_age, reason}} for every
        customer on credit hold as of `as_of_date`.

        `as_of_date` today or later: read the live flag straight off
        res.partner -- it is re-evaluated by the nightly cron, a payment, or
        Re-evaluate Now, so it is already "current".

        A date in the past: nothing stores historical hold status directly,
        but the event log does -- the latest hold/release event for a
        customer at or before that date says what was true then. A customer
        is on hold as of that date if that latest event is a 'hold'.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)

        if self.as_of_date >= today:
            domain = [('credit_hold', '=', True)]
            domain += self._customer_domain('id')
            partners = self.env['res.partner'].sudo().search(domain)
            return {
                partner: {
                    'invoices': partner.credit_hold_invoice_ids,
                    'hold_date': partner.credit_hold_date,
                    'amount': partner.credit_hold_amount,
                    'max_age': partner.credit_hold_max_age_days,
                    'reason': partner.credit_hold_warning,
                }
                for partner in partners
            }

        cutoff = fields.Datetime.to_datetime(self.as_of_date) + timedelta(days=1)
        domain = [('event_date', '<', cutoff)]
        domain += self._customer_domain()
        events = self.env['res.partner.credit.hold.event'].sudo().search(
            domain, order='partner_id, event_date desc')

        latest_by_partner = {}
        for event in events:
            latest_by_partner.setdefault(event.partner_id, event)

        result = {}
        for partner, event in latest_by_partner.items():
            if event.event_type != 'hold':
                continue
            result[partner] = {
                'invoices': event.invoice_ids,
                'hold_date': event.event_date,
                'amount': event.amount,
                'max_age': event.max_age_days,
                'reason': _(
                    "%(count)s invoice(s) totalling %(amount)s were more than "
                    "180 days overdue (oldest %(age)s days) as of this date.",
                    count=len(event.invoice_ids), amount=event.amount, age=event.max_age_days,
                ),
            }
        return result

    def _get_report_data(self):
        self.ensure_one()
        state = self._current_hold_state()

        customers = []
        for partner, info in state.items():
            invoices = info['invoices']
            projects = _projects_for(self.env, partner, invoices)
            customers.append({
                'partner': partner,
                'hold_date': info['hold_date'],
                'amount': info['amount'],
                'max_age': info['max_age'],
                'reason': info['reason'],
                'hold_days': (self.as_of_date - fields.Date.to_date(info['hold_date'])).days
                             if info['hold_date'] else 0,
                'rows': self._invoice_rows(invoices, self.as_of_date),
                'projects': self._project_rows(projects),
            })

        customers.sort(key=lambda c: c['partner'].display_name or '')
        return {'customers': customers}


def _generated_on_display(env):
    now = fields.Datetime.now()
    return fields.Datetime.context_timestamp(env.user, now).strftime('%d-%m-%Y %H:%M')


class ReportCreditHoldRemoved(models.AbstractModel):
    _name = 'report.account_extended_rk.report_credit_hold_removed_document'
    _description = 'Credit Hold Removed Details Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['credit.hold.removed.report.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'credit.hold.removed.report.wizard',
            'docs': wizard,
            'wizard': wizard,
            'report_data': wizard._get_report_data(),
            'company': self.env.company,
            'report_title': _("Credit Hold Removed Details"),
            'generated_on_display': _generated_on_display(self.env),
            'generated_by': self.env.user,
        }


class ReportCreditHoldCurrent(models.AbstractModel):
    _name = 'report.account_extended_rk.report_credit_hold_current_document'
    _description = 'Overall Current Credit Hold Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['credit.hold.current.report.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'credit.hold.current.report.wizard',
            'docs': wizard,
            'wizard': wizard,
            'report_data': wizard._get_report_data(),
            'company': self.env.company,
            'report_title': _("Overall Current Credit Hold"),
            'generated_on_display': _generated_on_display(self.env),
            'generated_by': self.env.user,
        }
