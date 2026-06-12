# -*- coding: utf-8 -*-
import io
from datetime import date

from odoo import api, fields, models, _
from odoo.tools import format_date

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class AccountLedgerExtended(models.AbstractModel):
    """Backend service for the Tally-like General / Outstanding partner
    ledgers. All heavy lifting (data + exports) lives here so the OWL client
    actions and the QWeb PDF reports share a single source of truth."""

    _name = 'account.ledger.extended.rk'
    _description = 'Accounting Ledger Extended (RK)'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _default_dates(self):
        """1st Jan of current year -> today (overridable in the UI)."""
        today = fields.Date.context_today(self)
        return {
            'date_from': date(today.year, 1, 1).isoformat(),
            'date_to': today.isoformat(),
        }

    @api.model
    def _currency_symbol(self):
        return self.env.company.currency_id.symbol or ''

    @api.model
    def search_partners(self, query=None, page=1, page_size=25):
        """Return a page of customers (partners holding receivable journal
        items) optionally filtered by the search query, along with paging
        metadata so the UI can offer next/previous navigation."""
        domain = [('account_type', '=', 'asset_receivable'),
                  ('parent_state', '=', 'posted')]
        if query:
            partners = self.env['res.partner'].sudo().search(
                [('name', 'ilike', query)]).ids
            domain.append(('partner_id', 'in', partners))
        groups = self.env['account.move.line'].read_group(
            domain, ['partner_id'], ['partner_id'])
        result = []
        for g in groups:
            if not g.get('partner_id'):
                continue
            pid, name = g['partner_id']
            result.append({'id': pid, 'name': name})
        result.sort(key=lambda p: (p['name'] or '').lower())

        total = len(result)
        page = max(1, int(page or 1))
        page_size = max(1, int(page_size or 25))
        pages = max(1, -(-total // page_size))  # ceil division
        page = min(page, pages)
        start = (page - 1) * page_size
        return {
            'partners': result[start:start + page_size],
            'total': total,
            'page': page,
            'pages': pages,
        }

    def _aml_domain(self, partner_id, date_to=None, date_from=None):
        domain = [
            ('partner_id', '=', partner_id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
        ]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain

    @staticmethod
    def _narration(line):
        """Build a Tally-like narration.

        * Invoices / credit notes -> the invoice line item descriptions.
        * Payments -> the payment memo.
        * Anything else -> the journal item label / move reference.
        """
        move = line.move_id
        if move.move_type in ('out_invoice', 'out_refund', 'in_invoice',
                              'in_refund'):
            # The "Add a note" lines (display_type='line_note') on the invoice
            notes = [n.strip() for n in move.line_ids.filtered(
                lambda l: l.display_type == 'line_note').mapped('name') if n]
            if notes:
                return ', '.join(notes)
        payment = getattr(move, 'payment_id', False) or \
            getattr(move, 'origin_payment_id', False)
        if payment:
            memo = payment.memo or move.ref or line.name
            if memo:
                return memo
        # Fallback: journal item label, then move reference, then type label
        if line.name:
            return line.name
        if move.ref:
            return move.ref
        return dict(move._fields['move_type'].selection).get(
            move.move_type, move.move_type)

    # ------------------------------------------------------------------
    # General Ledger
    # ------------------------------------------------------------------
    @api.model
    def get_general_ledger(self, partner_id, date_from, date_to):
        partner = self.env['res.partner'].browse(int(partner_id))
        AML = self.env['account.move.line']

        # Opening balance (everything strictly before date_from)
        opening_lines = AML.search(
            self._aml_domain(partner_id, date_to=False))
        opening = 0.0
        if date_from:
            opening_lines = AML.search(
                self._aml_domain(partner_id) +
                [('date', '<', date_from)])
            opening = sum(opening_lines.mapped('debit')) - \
                sum(opening_lines.mapped('credit'))

        lines = AML.search(
            self._aml_domain(partner_id, date_to=date_to, date_from=date_from),
            order='date asc, id asc')

        rows = []
        balance = opening
        total_debit = total_credit = 0.0
        for line in lines:
            balance += line.debit - line.credit
            total_debit += line.debit
            total_credit += line.credit
            rows.append({
                'id': line.id,
                'move_id': line.move_id.id,
                'date': format_date(self.env, line.date),
                'move_name': line.move_id.name,
                'journal': line.journal_id.code,
                'narration': self._narration(line),
                'debit': line.debit,
                'credit': line.credit,
                'balance': balance,
            })
        return {
            'partner': {'id': partner.id, 'name': partner.display_name},
            'currency': self._currency_symbol(),
            'date_from': date_from,
            'date_to': date_to,
            'opening_balance': opening,
            'rows': rows,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'closing_balance': balance,
        }

    # ------------------------------------------------------------------
    # Outstanding Ledger
    # ------------------------------------------------------------------
    @api.model
    def get_outstanding_ledger(self, partner_id, date_from, date_to):
        partner = self.env['res.partner'].browse(int(partner_id))
        domain = [
            ('partner_id', '=', int(partner_id)),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in',
             ('not_paid', 'partial', 'in_payment')),
            ('amount_residual', '!=', 0),
        ]
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        moves = self.env['account.move'].search(
            domain, order='invoice_date asc, name asc')

        rows = []
        total_due = total_residual = 0.0
        for move in moves:
            sign = -1 if move.move_type == 'out_refund' else 1
            total_due += move.amount_total_signed
            total_residual += move.amount_residual * sign
            rows.append({
                'id': move.id,
                'date': format_date(self.env, move.invoice_date),
                'due_date': format_date(self.env, move.invoice_date_due),
                'move_name': move.name,
                'narration': (move.ref or move.invoice_origin or
                              (move.move_type == 'out_refund' and 'Credit Note')
                              or 'Customer Invoice'),
                'amount_total': move.amount_total_signed,
                'residual': move.amount_residual * sign,
                'overdue': bool(move.invoice_date_due and
                                move.invoice_date_due < fields.Date.context_today(self)),
            })
        return {
            'partner': {'id': partner.id, 'name': partner.display_name},
            'currency': self._currency_symbol(),
            'date_from': date_from,
            'date_to': date_to,
            'rows': rows,
            'total_amount': total_due,
            'total_residual': total_residual,
        }

    # ------------------------------------------------------------------
    # Verification / email toggle (used by the Outstanding Ledger UI)
    # ------------------------------------------------------------------
    @api.model
    def get_partner_settings(self, partner_id):
        p = self.env['res.partner'].browse(int(partner_id))
        return {
            'verified': p.ledger_verified_by_accountant,
            'verified_by': p.ledger_verified_by.name or '',
            'email_enabled': p.ledger_email_enabled,
            'has_email': bool(p.email),
        }

    @api.model
    def verify_partner(self, partner_id):
        p = self.env['res.partner'].browse(int(partner_id))
        p.action_verify_for_ledger()
        return self.get_partner_settings(partner_id)

    @api.model
    def unverify_partner(self, partner_id):
        p = self.env['res.partner'].browse(int(partner_id))
        p.action_unverify_for_ledger()
        return self.get_partner_settings(partner_id)

    @api.model
    def set_partner_email_enabled(self, partner_id, enabled):
        p = self.env['res.partner'].browse(int(partner_id))
        p.ledger_email_enabled = bool(enabled)
        return self.get_partner_settings(partner_id)

    @api.model
    def send_outstanding_email_now(self, partner_id):
        """Manually trigger the outstanding email for one customer (testing).
        Returns a status dict for the UI to display."""
        p = self.env['res.partner'].browse(int(partner_id))
        if not p.email:
            return {'sent': False, 'message': 'No email set on this customer.'}
        sent = p.send_outstanding_email()
        if not sent:
            return {'sent': False,
                    'message': 'No outstanding invoices to send.'}
        return {'sent': True, 'message': 'Outstanding email sent to %s.'
                % p.email}

    # ------------------------------------------------------------------
    # XLSX export (shared by both ledgers)
    # ------------------------------------------------------------------
    def get_xlsx_report(self, data, response):
        report_type = data.get('report_type', 'general')
        if report_type == 'general':
            content = self.get_general_ledger(
                data['partner_id'], data['date_from'], data['date_to'])
            self._write_general_xlsx(content, response)
        else:
            content = self.get_outstanding_ledger(
                data['partner_id'], data['date_from'], data['date_to'])
            self._write_outstanding_xlsx(content, response)

    @staticmethod
    def _dc(value, suffix=None, currency=''):
        """Tally-style amount: currency, absolute value, then Dr/Cr."""
        if not value:
            return ''
        tag = suffix or ('Dr' if value >= 0 else 'Cr')
        prefix = (currency + ' ') if currency else ''
        return '%s%.2f %s' % (prefix, abs(value), tag)

    def _xlsx_formats(self, wb):
        return {
            'title': wb.add_format({'font_size': 16, 'bold': True,
                                    'align': 'center', 'font_color': '#f25d23'}),
            'sub': wb.add_format({'font_size': 10, 'align': 'center',
                                  'italic': True}),
            'head': wb.add_format(
                {'bold': True, 'font_size': 10, 'border': 1, 'align': 'center',
                 'bg_color': '#f25d23', 'font_color': 'white'}),
            'cell': wb.add_format({'font_size': 10, 'border': 1}),
            'num': wb.add_format(
                {'font_size': 10, 'border': 1, 'align': 'right'}),
            'total': wb.add_format(
                {'bold': True, 'font_size': 10, 'border': 1,
                 'align': 'right', 'bg_color': '#fde3d7'}),
            'total_lbl': wb.add_format(
                {'bold': True, 'font_size': 10, 'border': 1,
                 'bg_color': '#fde3d7'}),
        }

    def _write_general_xlsx(self, content, response):
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = wb.add_worksheet('General Ledger')
        f = self._xlsx_formats(wb)
        sheet.set_column(0, 0, 12)
        sheet.set_column(1, 2, 18)
        sheet.set_column(3, 3, 40)
        sheet.set_column(4, 6, 16)
        sheet.merge_range('A1:G1', _('General Ledger'), f['title'])
        sheet.merge_range(
            'A2:G2',
            '%s  |  %s to %s' % (content['partner']['name'],
                                 content['date_from'], content['date_to']),
            f['sub'])
        headers = ['Date', 'Voucher', 'Journal', 'Narration', 'Debit',
                   'Credit', 'Balance']
        row = 3
        for col, h in enumerate(headers):
            sheet.write(row, col, h, f['head'])
        row += 1
        cur = content['currency']
        sheet.write(row, 3, _('Opening Balance'), f['total_lbl'])
        sheet.write(row, 6, self._dc(content['opening_balance'], currency=cur), f['total'])
        row += 1
        for r in content['rows']:
            sheet.write(row, 0, r['date'], f['cell'])
            sheet.write(row, 1, r['move_name'], f['cell'])
            sheet.write(row, 2, r['journal'] or '', f['cell'])
            sheet.write(row, 3, r['narration'], f['cell'])
            sheet.write(row, 4, self._dc(r['debit'], 'Dr', cur), f['num'])
            sheet.write(row, 5, self._dc(r['credit'], 'Cr', cur), f['num'])
            sheet.write(row, 6, self._dc(r['balance'], currency=cur), f['num'])
            row += 1
        sheet.write(row, 3, _('Total'), f['total_lbl'])
        sheet.write(row, 4, self._dc(content['total_debit'], 'Dr', cur), f['total'])
        sheet.write(row, 5, self._dc(content['total_credit'], 'Cr', cur), f['total'])
        sheet.write(row, 6, self._dc(content['closing_balance'], currency=cur), f['total'])
        wb.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()

    def _write_outstanding_xlsx(self, content, response):
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = wb.add_worksheet('Outstanding Ledger')
        f = self._xlsx_formats(wb)
        sheet.set_column(0, 1, 14)
        sheet.set_column(2, 2, 18)
        sheet.set_column(3, 3, 40)
        sheet.set_column(4, 5, 16)
        sheet.merge_range('A1:F1', _('Outstanding Ledger'), f['title'])
        sheet.merge_range(
            'A2:F2',
            '%s  |  as on %s' % (content['partner']['name'],
                                 content['date_to']),
            f['sub'])
        headers = ['Date', 'Due Date', 'Invoice', 'Narration', 'Invoice Amount',
                   'Outstanding']
        row = 3
        for col, h in enumerate(headers):
            sheet.write(row, col, h, f['head'])
        row += 1
        cur = content['currency']
        for r in content['rows']:
            sheet.write(row, 0, r['date'], f['cell'])
            sheet.write(row, 1, r['due_date'] or '', f['cell'])
            sheet.write(row, 2, r['move_name'], f['cell'])
            sheet.write(row, 3, r['narration'], f['cell'])
            sheet.write(row, 4, self._dc(r['amount_total'], currency=cur), f['num'])
            sheet.write(row, 5, self._dc(r['residual'], currency=cur), f['num'])
            row += 1
        sheet.write(row, 3, _('Total Outstanding'), f['total_lbl'])
        sheet.write(row, 4, self._dc(content['total_amount'], currency=cur), f['total'])
        sheet.write(row, 5, self._dc(content['total_residual'], currency=cur), f['total'])
        wb.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
