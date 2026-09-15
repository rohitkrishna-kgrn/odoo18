import base64
import io
import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        help="Show the invoice table for each customer in the report.")
    show_project_details = fields.Boolean(
        string='Linked Projects', default=True,
        help="Show the linked-projects table for each customer in the report.")

    file_data = fields.Binary(string='File', readonly=True, attachment=False)
    file_name = fields.Char(string='File Name', readonly=True)

    # wkhtmltopdf is a native, WebKit-based renderer that holds the whole
    # document in memory while it works. Confirmed live on this box
    # (2026-09-15): a single-pass render of an unfiltered Overall Current run
    # -- 704 on-hold customers -- grew it to ~1.5GB RSS and the kernel
    # OOM-killer killed it, which took the whole odoo18 service down for
    # every user for about 10 seconds while systemd restarted it. Rather than
    # refuse large runs, `_render_pdf_bytes` renders them in bounded chunks
    # of this many customers each and merges the results -- wkhtmltopdf exits
    # and frees its memory between chunks instead of accumulating across the
    # whole run.
    _PDF_BATCH_SIZE = 50

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}

    def action_download(self):
        """Render, compress and download the PDF."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        name = '%s_%s.pdf' % (self._export_basename, today)
        self.write({
            'file_data': base64.b64encode(self._render_pdf_bytes()),
            'file_name': name,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/file_data/%s?download=true' % (
                self._name, self.id, name),
            'target': 'self',
        }

    def _render_pdf_bytes(self):
        self.ensure_one()
        partner_ids = self._matching_partner_ids()
        if len(partner_ids) <= self._PDF_BATCH_SIZE:
            content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
                self._report_xmlid, res_ids=self.ids)
        else:
            content = self._render_pdf_batched(partner_ids)
        return self._compress_pdf(content)

    def _render_pdf_batched(self, partner_ids):
        """Render in chunks of `_PDF_BATCH_SIZE` customers and merge with
        pikepdf. Each chunk is its own `_render_qweb_pdf` call -- its own
        wkhtmltopdf subprocess that starts, renders only that chunk's
        customers, and exits, so peak memory is bounded by one chunk, not
        the whole run. `only_partner_ids` scopes `_get_report_data` down to
        the chunk (so the DB-side work is also done once per customer, not
        once per customer per chunk); `start_index` keeps the "1. Customer"
        numbering continuous across chunks instead of restarting at 1 each
        time; `suppress_footer` keeps the "Generated: ..." line off every
        chunk but the last, since it would otherwise land after every
        chunk's final customer, not just the document's.
        """
        import pikepdf
        batches = [partner_ids[i:i + self._PDF_BATCH_SIZE]
                   for i in range(0, len(partner_ids), self._PDF_BATCH_SIZE)]
        merged = pikepdf.Pdf.new()
        opened = []
        try:
            for index, batch in enumerate(batches):
                content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
                    self._report_xmlid, res_ids=self.ids,
                    data={
                        'only_partner_ids': batch,
                        'start_index': index * self._PDF_BATCH_SIZE,
                        'suppress_footer': index < len(batches) - 1,
                    })
                src = pikepdf.open(io.BytesIO(content))
                opened.append(src)
                merged.pages.extend(src.pages)
            out = io.BytesIO()
            merged.save(out)
            return out.getvalue()
        finally:
            for src in opened:
                src.close()
            merged.close()

    def _compress_pdf(self, raw):
        """Recompress wkhtmltopdf's (or the merged) output with pikepdf --
        rewrites content streams with Flate compression and collapses the
        object table into object streams. This is lossless (nothing
        rendered changes) and works purely on what wkhtmltopdf already
        produced, so it does nothing for the peak memory wkhtmltopdf itself
        needs while rendering -- `_render_pdf_batched` above is what bounds
        that. Falls back to the uncompressed bytes if pikepdf can't process
        this particular PDF, rather than fail the whole download over a
        compression step.
        """
        try:
            import pikepdf
            with pikepdf.open(io.BytesIO(raw)) as pdf:
                out = io.BytesIO()
                pdf.save(
                    out, compress_streams=True,
                    object_stream_mode=pikepdf.ObjectStreamMode.generate)
                compressed = out.getvalue()
        except Exception:
            _logger.warning(
                "Credit Hold Report: PDF compression failed, sending "
                "uncompressed", exc_info=True)
            return raw
        return compressed if len(compressed) < len(raw) else raw

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

    def _events_domain(self):
        domain = [
            ('event_type', '=', 'release'),
            ('event_date', '>=', fields.Datetime.to_datetime(self.date_from)),
            ('event_date', '<', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)),
        ]
        return domain + self._customer_domain()

    def _matching_partner_ids(self):
        """Cheap: which customers will appear, with none of the per-customer
        project-lookup work `_get_report_data` does for each one.
        """
        self.ensure_one()
        events = self.env['res.partner.credit.hold.event'].sudo().search(self._events_domain())
        return events.mapped('partner_id').ids

    def _get_report_data(self, only_partner_ids=None):
        self.ensure_one()
        today = fields.Date.context_today(self)

        domain = self._events_domain()
        if only_partner_ids is not None:
            domain += [('partner_id', 'in', only_partner_ids)]

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

    def _current_hold_state(self, only_partner_ids=None):
        """{partner: {invoices, hold_date, amount, max_age, reason}} for every
        customer on credit hold as of `as_of_date`.

        `as_of_date` today or later: read the live flag straight off
        res.partner -- it is re-evaluated by the nightly cron, a payment, or
        Re-evaluate Now, so it is already "current".

        A date in the past: nothing stores historical hold status directly,
        but the event log does -- the latest hold/release event for a
        customer at or before that date says what was true then. A customer
        is on hold as of that date if that latest event is a 'hold'.

        `only_partner_ids`, when given, scopes both branches' queries down
        to that set -- used to render one batch at a time without redoing
        the query for every customer on every batch.
        """
        self.ensure_one()
        today = fields.Date.context_today(self)

        if self.as_of_date >= today:
            domain = [('credit_hold', '=', True)]
            domain += self._customer_domain('id')
            if only_partner_ids is not None:
                domain += [('id', 'in', only_partner_ids)]
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
        if only_partner_ids is not None:
            domain += [('partner_id', 'in', only_partner_ids)]
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

    def _matching_partner_ids(self):
        """Cheap: which customers will appear, with none of the per-customer
        project-lookup work `_get_report_data` does for each one.
        """
        self.ensure_one()
        return [partner.id for partner in self._current_hold_state()]

    def _get_report_data(self, only_partner_ids=None):
        self.ensure_one()
        state = self._current_hold_state(only_partner_ids=only_partner_ids)

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
        data = data or {}
        wizard = self.env['credit.hold.removed.report.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'credit.hold.removed.report.wizard',
            'docs': wizard,
            'wizard': wizard,
            'report_data': wizard._get_report_data(
                only_partner_ids=data.get('only_partner_ids')),
            'company': self.env.company,
            'report_title': _("Credit Hold Removed Details"),
            'generated_on_display': _generated_on_display(self.env),
            'generated_by': self.env.user,
            'start_index': data.get('start_index', 0),
            'suppress_footer': data.get('suppress_footer', False),
        }


class ReportCreditHoldCurrent(models.AbstractModel):
    _name = 'report.account_extended_rk.report_credit_hold_current_document'
    _description = 'Overall Current Credit Hold Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        wizard = self.env['credit.hold.current.report.wizard'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'credit.hold.current.report.wizard',
            'docs': wizard,
            'wizard': wizard,
            'report_data': wizard._get_report_data(
                only_partner_ids=data.get('only_partner_ids')),
            'company': self.env.company,
            'report_title': _("Overall Current Credit Hold"),
            'generated_on_display': _generated_on_display(self.env),
            'generated_by': self.env.user,
            'start_index': data.get('start_index', 0),
            'suppress_footer': data.get('suppress_footer', False),
        }
