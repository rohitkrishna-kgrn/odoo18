# -*- coding: utf-8 -*-
import io
import json
import logging
import xlsxwriter
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

NO_PM_LABEL = 'No Project Manager'


class AgedReceivablePMReport(models.TransientModel):
    _inherit = 'age.receivable.report'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format(self, value):
        return "{:,.2f}".format(value)

    def _get_pm_cache(self):
        """Return three look-up dicts built from project.project records.

        so_to_pm      : {sale_order_id       -> (user_id, user_name)}
        aa_to_pm      : {str(analytic_acct_id) -> (user_id, user_name)}
        partner_to_pm : {res.partner.id       -> (user_id, user_name)}
        """
        try:
            projects = self.env['project.project'].search([('user_id', '!=', False)])
        except Exception:
            return {}, {}, {}
        so_to_pm, aa_to_pm, partner_to_pm = {}, {}, {}
        for proj in projects:
            pm = (proj.user_id.id, proj.user_id.name)
            so = getattr(proj, 'sale_order_id', False)
            if so:
                so_to_pm[so.id] = pm
            aa = getattr(proj, 'analytic_account_id', False)
            if aa:
                aa_to_pm[str(aa.id)] = pm
            # Fallback: match by project customer (partner_id is standard on project.project)
            partner = getattr(proj, 'partner_id', False)
            if partner and getattr(partner, 'id', False) and partner.id not in partner_to_pm:
                partner_to_pm[partner.id] = pm
        return so_to_pm, aa_to_pm, partner_to_pm

    def _get_pm_mapping(self, move_lines):
        """Return {move_line.id: (pm_id, pm_name) or None}."""
        if not move_lines:
            return {}

        so_to_pm, aa_to_pm, partner_to_pm = self._get_pm_cache()
        pm_mapping = {ml.id: None for ml in move_lines}

        if not so_to_pm and not aa_to_pm and not partner_to_pm:
            return pm_mapping

        has_sale = 'sale.order' in self.env.registry
        move_ids = list(set(move_lines.mapped('move_id.id')))
        move_to_pm = {}

        for move in self.env['account.move'].browse(move_ids):
            pm = None

            # 1) Via invoice line → sale order line → sale order → project
            if so_to_pm and has_sale:
                try:
                    for inv_line in move.invoice_line_ids:
                        for sl in getattr(inv_line, 'sale_line_ids', []):
                            if sl.order_id.id in so_to_pm:
                                pm = so_to_pm[sl.order_id.id]
                                break
                        if pm:
                            break
                except Exception:
                    pass

            # 2) Via analytic distribution on invoice lines
            if not pm and aa_to_pm:
                try:
                    for inv_line in move.invoice_line_ids:
                        dist = getattr(inv_line, 'analytic_distribution', None) or {}
                        for aa_id_str in dist.keys():
                            if aa_id_str in aa_to_pm:
                                pm = aa_to_pm[aa_id_str]
                                break
                        if pm:
                            break
                except Exception:
                    pass

            # 3) Via invoice_origin (e.g. "S00001")
            if not pm and so_to_pm and has_sale and move.invoice_origin:
                try:
                    for so_name in move.invoice_origin.split(','):
                        so_name = so_name.strip()
                        so = self.env['sale.order'].search(
                            [('name', '=', so_name)], limit=1)
                        if so and so.id in so_to_pm:
                            pm = so_to_pm[so.id]
                            break
                except Exception:
                    pass

            # 4) Via invoice partner → project customer (partner_id on project.project)
            if not pm and partner_to_pm:
                try:
                    partner_id = move.partner_id.id
                    if partner_id:
                        pm = partner_to_pm.get(partner_id)
                    # Also try commercial partner (handles contact vs company)
                    if not pm:
                        commercial_id = getattr(
                            move.partner_id, 'commercial_partner_id', False)
                        if commercial_id and commercial_id.id != partner_id:
                            pm = partner_to_pm.get(commercial_id.id)
                except Exception:
                    pass

            if pm:
                move_to_pm[move.id] = pm

        for ml in move_lines:
            pm_mapping[ml.id] = move_to_pm.get(ml.move_id.id)

        _logger.debug(
            "PM mapping: %d lines, %d mapped to a PM",
            len(pm_mapping),
            sum(1 for v in pm_mapping.values() if v is not None),
        )
        return pm_mapping

    def _aging_buckets(self, val, ref_date):
        """Compute and attach raw + formatted aging bucket fields to a read() dict."""
        fmt = self._format
        diff = 0
        if val.get('date_maturity'):
            diff = (ref_date - val['date_maturity']).days

        val['raw_amount_currency'] = val['amount_currency']
        val['raw_debit'] = val['debit']
        val['diff0'] = val['debit'] if diff <= 0 else 0.0
        val['diff1'] = val['debit'] if 0 < diff <= 30 else 0.0
        val['diff2'] = val['debit'] if 30 < diff <= 60 else 0.0
        val['diff3'] = val['debit'] if 60 < diff <= 90 else 0.0
        val['diff4'] = val['debit'] if 90 < diff <= 120 else 0.0
        val['diff5'] = val['debit'] if diff > 120 else 0.0
        for k in ['diff0', 'diff1', 'diff2', 'diff3', 'diff4', 'diff5']:
            val[f'raw_{k}'] = val[k]
        val['amount_currency'] = fmt(val['amount_currency'])
        val['debit'] = fmt(val['debit'])
        for k in ['diff0', 'diff1', 'diff2', 'diff3', 'diff4', 'diff5']:
            val[k] = fmt(val[f'raw_{k}'])
        return val

    def _partner_total(self, move_line_data, currency_id, partner_id):
        fmt = self._format
        raw = lambda key: sum(v[f'raw_{key}'] for v in move_line_data)
        return {
            'debit_sum': raw('debit'),
            'diff0_sum': round(raw('diff0'), 2),
            'diff1_sum': round(raw('diff1'), 2),
            'diff2_sum': round(raw('diff2'), 2),
            'diff3_sum': round(raw('diff3'), 2),
            'diff4_sum': round(raw('diff4'), 2),
            'diff5_sum': round(raw('diff5'), 2),
            'debit_sum_display': fmt(raw('debit')),
            'diff0_sum_display': fmt(round(raw('diff0'), 2)),
            'diff1_sum_display': fmt(round(raw('diff1'), 2)),
            'diff2_sum_display': fmt(round(raw('diff2'), 2)),
            'diff3_sum_display': fmt(round(raw('diff3'), 2)),
            'diff4_sum_display': fmt(round(raw('diff4'), 2)),
            'diff5_sum_display': fmt(round(raw('diff5'), 2)),
            'currency_id': currency_id,
            'partner_id': partner_id,
        }

    def _zero_total(self, currency_id):
        fmt = self._format
        t = {f'diff{i}_sum': 0.0 for i in range(6)}
        t['debit_sum'] = 0.0
        for k in list(t.keys()):
            t[f'{k}_display'] = fmt(0.0)
        t['currency_id'] = currency_id
        return t

    def _add_to_total(self, total, partner_total):
        total['debit_sum'] = round(total['debit_sum'] + partner_total['debit_sum'], 2)
        for i in range(6):
            total[f'diff{i}_sum'] = round(
                total[f'diff{i}_sum'] + partner_total[f'diff{i}_sum'], 2)

    def _finalize_total(self, total):
        fmt = self._format
        total['debit_sum_display'] = fmt(total['debit_sum'])
        for i in range(6):
            total[f'diff{i}_sum_display'] = fmt(total[f'diff{i}_sum'])

    def _read_fields(self):
        return ['name', 'move_name', 'date', 'amount_currency', 'account_id',
                'date_maturity', 'currency_id', 'debit', 'move_id']

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @api.model
    def get_pm_list(self):
        """Return [{id, name}] of all users who manage at least one project."""
        try:
            projects = self.env['project.project'].search([('user_id', '!=', False)])
            seen = {}
            for proj in projects:
                u = proj.user_id
                seen[u.id] = u.name
            return [{'id': uid, 'name': name} for uid, name in seen.items()]
        except Exception:
            return []

    @api.model
    def get_pm_report_data(self, date, partner_ids, pm_ids,
                           group_by_pm, date_from=False):
        """Main data-fetch method used by the OWL component.

        Fast-paths to the base get_filter_values when no PM features are
        requested so the ordinary report is never slower than before.
        Returns a flat partner-keyed dict when group_by_pm=False, or a
        richer PM-grouped structure when group_by_pm=True.
        """
        # Fast path: no PM features needed — use the base implementation
        if not pm_ids and not group_by_pm:
            return super().get_filter_values(
                date or '', partner_ids, date_from or '')

        domain = [
            ('parent_state', '=', 'posted'),
            ('account_type', '=', 'asset_receivable'),
            ('reconciled', '=', False),
        ]
        if date:
            domain.append(('date', '<=', date))
        if date_from:
            domain.append(('date', '>=', date_from))

        all_lines = self.env['account.move.line'].search(domain)
        currency_id = self.env.company.currency_id.symbol
        ref_date = (fields.Date.from_string(date)
                    if date and isinstance(date, str)
                    else (date or fields.Date.today()))

        try:
            pm_map = self._get_pm_mapping(all_lines)
        except Exception:
            pm_map = {ml.id: None for ml in all_lines}

        # Apply PM filter
        if pm_ids:
            pm_set = set(pm_ids)
            all_lines = all_lines.filtered(
                lambda ml: pm_map.get(ml.id) and pm_map[ml.id][0] in pm_set
            )

        # Apply partner filter
        if partner_ids:
            p_set = set(partner_ids)
            all_lines = all_lines.filtered(
                lambda ml: ml.partner_id.id in p_set)

        if not group_by_pm:
            try:
                return self._flat_result(all_lines, ref_date, currency_id)
            except Exception as exc:
                _logger.error("_flat_result failed: %s", exc, exc_info=True)
                return super().get_filter_values(date or '', partner_ids, date_from or '')
        else:
            try:
                return self._grouped_result(all_lines, ref_date, currency_id,
                                            pm_map)
            except Exception as exc:
                _logger.error("_grouped_result failed: %s", exc, exc_info=True)
                # Surface the error so the JS can show a meaningful message
                # instead of silently keeping stale flat data.
                raise

    # ------------------------------------------------------------------
    # Internal result builders
    # ------------------------------------------------------------------

    def _flat_result(self, move_lines, ref_date, currency_id):
        """Same dict shape as base get_filter_values."""
        partner_total = {}
        move_line_list = {}
        partners = move_lines.mapped('partner_id')
        for partner in partners:
            lines = move_lines.filtered(lambda ml: ml.partner_id == partner)
            data = lines.read(self._read_fields())
            for val in data:
                self._aging_buckets(val, ref_date)
            move_line_list[partner.name] = data
            partner_total[partner.name] = self._partner_total(
                data, currency_id, partner.id)
        move_line_list['partner_totals'] = partner_total
        return move_line_list

    def _grouped_result(self, move_lines, ref_date, currency_id, pm_map):
        """PM-grouped structure consumed by the OWL component and reports."""
        # Build intermediate dict: pm_name -> partner_name -> recordset
        pm_buckets = {}
        pm_ids_map = {}   # pm_name -> pm_id (for later reference)

        for ml in move_lines:
            pm_info = pm_map.get(ml.id)
            pm_name = pm_info[1] if pm_info else NO_PM_LABEL
            pm_id_val = pm_info[0] if pm_info else 0
            pm_ids_map.setdefault(pm_name, pm_id_val)

            partner_name = ml.partner_id.name or 'Unknown'
            pm_buckets.setdefault(pm_name, {})
            pm_buckets[pm_name].setdefault(partner_name, {
                'partner_id': ml.partner_id.id,
                'lines': self.env['account.move.line'],
            })
            pm_buckets[pm_name][partner_name]['lines'] |= ml

        pm_list = []
        pm_data = {}
        pm_totals = {}
        grand = self._zero_total(currency_id)

        for pm_name, partners in pm_buckets.items():
            pm_list.append(pm_name)
            pm_total = self._zero_total(currency_id)
            partner_list = []
            partner_data = {}
            partner_totals = {}

            for partner_name, pinfo in partners.items():
                lines = pinfo['lines']
                data = lines.read(self._read_fields())
                for val in data:
                    self._aging_buckets(val, ref_date)
                ptotal = self._partner_total(data, currency_id,
                                             pinfo['partner_id'])
                partner_list.append(partner_name)
                partner_data[partner_name] = data
                partner_totals[partner_name] = ptotal
                self._add_to_total(pm_total, ptotal)

            self._finalize_total(pm_total)
            pm_total['currency_id'] = currency_id
            pm_data[pm_name] = {
                'pm_id': pm_ids_map[pm_name],
                'partner_list': partner_list,
                'partner_data': partner_data,
                'partner_totals': partner_totals,
            }
            pm_totals[pm_name] = pm_total
            self._add_to_total(grand, pm_total)

        self._finalize_total(grand)
        grand['currency_id'] = currency_id

        return {
            'grouped': True,
            'pm_list': pm_list,
            'pm_data': pm_data,
            'pm_totals': pm_totals,
            'grand_total': grand,
            'currency': currency_id,
        }

    # ------------------------------------------------------------------
    # XLSX export (override to handle PM report action)
    # ------------------------------------------------------------------

    @api.model
    def get_xlsx_report(self, data, response, report_name, report_action):
        """Route to PM-aware XLSX builder when PM or grouped data is present."""
        parsed = json.loads(data)
        if parsed.get('grouped') or parsed.get('pm_list'):
            self._build_pm_xlsx(parsed, response, report_name)
        else:
            return super().get_xlsx_report(data, response, report_name,
                                           report_action)

    def _build_pm_xlsx(self, data, response, report_name):
        """Write XLSX for the PM-enhanced Aged Receivable report."""
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = wb.add_worksheet()

        # Formats
        head = wb.add_format(
            {'align': 'center', 'bold': True, 'font_size': 15})
        sub_head = wb.add_format(
            {'align': 'center', 'bold': True, 'font_size': 10,
             'border': 1, 'bg_color': '#D3D3D3'})
        filter_head = wb.add_format(
            {'align': 'center', 'bold': True, 'font_size': 10,
             'border': 1, 'bg_color': '#D3D3D3'})
        filter_body = wb.add_format(
            {'align': 'center', 'bold': True, 'font_size': 10})
        pm_head_fmt = wb.add_format(
            {'bold': True, 'font_size': 10, 'border': 1,
             'bg_color': '#4472C4', 'font_color': '#FFFFFF'})
        partner_fmt = wb.add_format(
            {'bold': True, 'font_size': 10, 'border': 1,
             'bg_color': '#D3D3D3'})
        txt = wb.add_format({'font_size': 10, 'border': 1})
        num = wb.add_format(
            {'font_size': 10, 'border': 1, 'num_format': '#,##0.00'})
        total_num = wb.add_format(
            {'bold': True, 'font_size': 10, 'border': 1,
             'bg_color': '#D3D3D3', 'num_format': '#,##0.00'})
        grand_fmt = wb.add_format(
            {'bold': True, 'font_size': 10, 'border': 1,
             'bg_color': '#808080', 'font_color': '#FFFFFF',
             'num_format': '#,##0.00'})

        # Column widths
        sheet.set_column(0, 0, 30)
        sheet.set_column(1, 1, 20)
        for c in range(2, 15):
            sheet.set_column(c, c, 15)

        filters = data.get('filters', {})
        end_date = filters.get('end_date', '')
        start_date = filters.get('start_date', '')
        pm_filter = filters.get('pm', [])
        partner_filter = filters.get('partner', [])

        # Title & filter rows
        sheet.write('A1', report_name, head)
        sheet.write('B3', 'Date Range', filter_head)
        sheet.write('B4', 'Project Manager', filter_head)
        sheet.write('B5', 'Partner', filter_head)
        if start_date or end_date:
            date_str = (f"{start_date} - {end_date}"
                        if start_date and end_date
                        else (start_date or end_date))
            sheet.merge_range('C3:G3', date_str, filter_body)
        if pm_filter:
            sheet.merge_range('C4:G4',
                              ', '.join(p.get('name', '') for p in pm_filter),
                              filter_body)
        if partner_filter:
            sheet.merge_range('C5:G5',
                              ', '.join(p.get('display_name', '')
                                        for p in partner_filter),
                              filter_body)

        # Column header row
        col_headers = [
            ' ', 'Invoice Date', 'Amount Currency', 'Currency',
            'Account', '', 'Expected Date', '',
            'At Date', '1-30', '31-60', '61-90', '91-120', 'Older', 'Total',
        ]
        header_row = 7
        for ci, h in enumerate(col_headers):
            sheet.write(header_row, ci, h, sub_head)

        row = header_row + 1
        grouped = data.get('grouped', False)

        if grouped:
            pm_list = data.get('pm_list', [])
            pm_data = data.get('pm_data', {})
            pm_totals = data.get('pm_totals', {})
            grand = data.get('grand_total', {})

            for pm_name in pm_list:
                # PM header
                sheet.merge_range(row, 0, row, 14,
                                  f'Project Manager: {pm_name}', pm_head_fmt)
                row += 1

                pdata = pm_data.get(pm_name, {})
                for partner_name in pdata.get('partner_list', []):
                    ptotal = pdata['partner_totals'][partner_name]
                    # Partner summary row
                    sheet.write(row, 0, partner_name, partner_fmt)
                    sheet.write(row, 1, ' ', partner_fmt)
                    sheet.write(row, 2, ' ', partner_fmt)
                    sheet.write(row, 3, ' ', partner_fmt)
                    sheet.merge_range(row, 4, row, 5, ' ', partner_fmt)
                    sheet.merge_range(row, 6, row, 7, ' ', partner_fmt)
                    sheet.write(row, 8, ptotal['diff0_sum'], total_num)
                    sheet.write(row, 9, ptotal['diff1_sum'], total_num)
                    sheet.write(row, 10, ptotal['diff2_sum'], total_num)
                    sheet.write(row, 11, ptotal['diff3_sum'], total_num)
                    sheet.write(row, 12, ptotal['diff4_sum'], total_num)
                    sheet.write(row, 13, ptotal['diff5_sum'], total_num)
                    sheet.write(row, 14, ptotal['debit_sum'], total_num)
                    row += 1

                    for rec in pdata['partner_data'].get(partner_name, []):
                        sheet.write(row, 0,
                                    (rec.get('move_name') or '') +
                                    (rec.get('name') or ''), txt)
                        sheet.write(row, 1, rec.get('date', ''), txt)
                        sheet.write(row, 2, rec.get('amount_currency', 0),
                                    num)
                        cur = rec.get('currency_id')
                        sheet.write(row, 3,
                                    cur[1] if isinstance(cur, (list, tuple))
                                    else (cur or ''), txt)
                        acc = rec.get('account_id')
                        sheet.merge_range(
                            row, 4, row, 5,
                            acc[1] if isinstance(acc, (list, tuple))
                            else (acc or ''), txt)
                        sheet.merge_range(
                            row, 6, row, 7,
                            rec.get('date_maturity', '') or '', txt)
                        for ci, k in enumerate(
                                ['diff0', 'diff1', 'diff2',
                                 'diff3', 'diff4', 'diff5'], start=8):
                            sheet.write(row, ci,
                                        rec.get(f'raw_{k}', 0), num)
                        sheet.write(row, 14, ' ', txt)
                        row += 1

                # PM total row
                pm_t = pm_totals.get(pm_name, {})
                sheet.merge_range(row, 0, row, 7,
                                  f'Total – {pm_name}', filter_head)
                for ci, k in enumerate(
                        ['diff0_sum', 'diff1_sum', 'diff2_sum',
                         'diff3_sum', 'diff4_sum', 'diff5_sum',
                         'debit_sum'], start=8):
                    sheet.write(row, ci, pm_t.get(k, 0), total_num)
                row += 1

            # Grand total
            sheet.merge_range(row, 0, row, 7, 'Grand Total', grand_fmt)
            for ci, k in enumerate(
                    ['diff0_sum', 'diff1_sum', 'diff2_sum',
                     'diff3_sum', 'diff4_sum', 'diff5_sum',
                     'debit_sum'], start=8):
                sheet.write(row, ci, grand.get(k, 0), grand_fmt)

        else:
            # Flat mode – same layout as base module
            for partner_name in data.get('move_lines', []):
                ptotal = data['total'][partner_name]
                sheet.write(row, 0, partner_name, txt)
                sheet.write(row, 1, ' ', txt)
                sheet.write(row, 2, ' ', txt)
                sheet.write(row, 3, ' ', txt)
                sheet.merge_range(row, 4, row, 5, ' ', txt)
                sheet.merge_range(row, 6, row, 7, ' ', txt)
                sheet.write(row, 8, ptotal['diff0_sum'], num)
                sheet.write(row, 9, ptotal['diff1_sum'], num)
                sheet.write(row, 10, ptotal['diff2_sum'], num)
                sheet.write(row, 11, ptotal['diff3_sum'], num)
                sheet.write(row, 12, ptotal['diff4_sum'], num)
                sheet.write(row, 13, ptotal['diff5_sum'], num)
                sheet.write(row, 14, ptotal['debit_sum'], num)
                row += 1
                for rec in data['data'].get(partner_name, []):
                    sheet.write(row, 0,
                                (rec.get('move_name') or '') +
                                (rec.get('name') or ''), txt)
                    sheet.write(row, 1, rec.get('date', ''), txt)
                    sheet.write(row, 2, rec.get('amount_currency', 0), num)
                    cur = rec.get('currency_id')
                    sheet.write(row, 3,
                                cur[1] if isinstance(cur, (list, tuple))
                                else (cur or ''), txt)
                    acc = rec.get('account_id')
                    sheet.merge_range(
                        row, 4, row, 5,
                        acc[1] if isinstance(acc, (list, tuple))
                        else (acc or ''), txt)
                    sheet.merge_range(
                        row, 6, row, 7,
                        rec.get('date_maturity', '') or '', txt)
                    for ci, k in enumerate(
                            ['diff0', 'diff1', 'diff2',
                             'diff3', 'diff4', 'diff5'], start=8):
                        sheet.write(row, ci, rec.get(f'raw_{k}', 0), num)
                    sheet.write(row, 14, ' ', txt)
                    row += 1

            # Grand total for flat mode
            grand = data.get('grand_total', {})
            sheet.merge_range(row, 0, row, 7, 'Total', filter_head)
            for ci, k in enumerate(
                    ['diff0_sum', 'diff1_sum', 'diff2_sum',
                     'diff3_sum', 'diff4_sum', 'diff5_sum',
                     'total_debit'], start=8):
                sheet.write(row, ci, grand.get(k, 0), total_num)

        wb.close()
        output.seek(0)
        response.stream.write(output.read())
        output.close()
