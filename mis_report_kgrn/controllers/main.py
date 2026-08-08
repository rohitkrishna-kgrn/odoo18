import json
import io
from datetime import datetime

from odoo import http
from odoo.http import request, content_disposition


class MisPerformanceExportController(http.Controller):
    """Excel export for the Performance Management dashboards.

    Sheet 1 is the fixed KPI summary (the on-screen list columns, one row
    per selected employee-month). Sheet 2, added only when "Task Include"
    is enabled, is a flat Task / Timesheet Detail sheet — one row per task,
    with Customer and Project alongside it.

    No DB queries here: everything in `sheet1` / `sheet2` is built
    client-side from data the browser already fetched through the ORM (and
    therefore already passed record rules / access rights), so this only
    formats data the current user was already allowed to see.
    """

    def _write_sheet(self, workbook, formats, sheet_def):
        name = (sheet_def.get('name') or 'Sheet')[:31] or 'Sheet'
        columns = sheet_def.get('columns') or []
        rows = sheet_def.get('rows') or []
        totals = sheet_def.get('totals') or {}

        sheet = workbook.add_worksheet(name)

        header_row = 0
        for c, col in enumerate(columns):
            sheet.write(header_row, c, col.get('label', col.get('name')), formats['header'])
            width = max(12, len(str(col.get('label', ''))) + 4)
            sheet.set_column(c, c, min(width, 34))
        sheet.freeze_panes(header_row + 1, 0)

        r = header_row + 1
        for row in rows:
            for c, col in enumerate(columns):
                name_ = col.get('name')
                ctype = col.get('type')
                value = row.get(name_)
                if ctype == 'monetary' or ctype == 'float':
                    sheet.write_number(r, c, float(value) if value else 0.0, formats['num'])
                elif ctype == 'percent':
                    sheet.write_number(r, c, float(value) if value else 0.0, formats['pct'])
                elif ctype == 'integer':
                    sheet.write_number(r, c, int(value) if value else 0, formats['int'])
                else:
                    sheet.write(r, c, '' if value in (None, False) else str(value), formats['text'])
            r += 1

        if rows and totals:
            for c, col in enumerate(columns):
                if c == 0:
                    sheet.write(r, c, 'Total', formats['total_label'])
                elif col.get('agg') and col.get('name') in totals:
                    sheet.write_number(r, c, float(totals[col['name']] or 0), formats['total_num'])
                else:
                    sheet.write(r, c, '', formats['total_label'])
            r += 1

        if r > header_row + 1:
            sheet.autofilter(header_row, 0, r - 1, max(len(columns) - 1, 0))

    @http.route('/mis_report_kgrn/export/performance_xlsx', type='http', auth='user', methods=['POST'], csrf=False)
    def export_performance_xlsx(self, **kw):
        import xlsxwriter

        raw = request.httprequest.get_data(as_text=True)
        payload = json.loads(raw or '{}')
        title = (payload.get('title') or 'Performance Report').strip() or 'Performance Report'
        subtitle = payload.get('subtitle') or ''
        sheet1 = payload.get('sheet1') or {}
        sheet2 = payload.get('sheet2')

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        formats = {
            'header': workbook.add_format({
                'bold': True, 'bg_color': '#714B67', 'font_color': '#ffffff',
                'border': 1, 'valign': 'vcenter', 'text_wrap': True,
            }),
            'text': workbook.add_format({'border': 1, 'valign': 'vcenter'}),
            'num': workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0.00'}),
            'int': workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0'}),
            'pct': workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '0.0"%"'}),
            'total_label': workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#e9ecef'}),
            'total_num': workbook.add_format({
                'bold': True, 'border': 1, 'bg_color': '#e9ecef', 'num_format': '#,##0.00',
            }),
        }

        self._write_sheet(workbook, formats, sheet1)
        if sheet2 and sheet2.get('rows'):
            self._write_sheet(workbook, formats, sheet2)

        workbook.close()
        output.seek(0)
        filename = f"{title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )
