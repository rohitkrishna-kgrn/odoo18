import json
import io
from datetime import datetime

from odoo import http
from odoo.http import request, content_disposition


class MisPerformanceExportController(http.Controller):
    """Excel export for the Performance Management dashboards.

    One summary row per selected employee-month (the fixed KPI columns the
    business asked for), followed by that employee's task/project/hours
    detail as collapsed Excel outline rows (click the +/- control to expand)
    — the closest real equivalent of "a dropdown inside each user" in a
    static Excel file.

    No DB queries here: `groups` are built client-side from data the browser
    already fetched through the ORM (and therefore already passed record
    rules / access rights), so this only formats data the current user was
    already allowed to see.
    """

    @http.route('/mis_report_kgrn/export/performance_xlsx', type='http', auth='user', methods=['POST'], csrf=False)
    def export_performance_xlsx(self, **kw):
        import xlsxwriter

        raw = request.httprequest.get_data(as_text=True)
        payload = json.loads(raw or '{}')
        title = (payload.get('title') or 'Performance Report').strip() or 'Performance Report'
        subtitle = payload.get('subtitle') or ''
        columns = payload.get('columns') or []
        groups = payload.get('groups') or []

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(title[:31] or 'Report')
        # Expand/collapse control sits on the summary row, above its (hidden)
        # detail rows.
        sheet.outline_settings(True, False, True, False)

        fmt_title = workbook.add_format({'bold': True, 'font_size': 14})
        fmt_meta = workbook.add_format({'italic': True, 'font_color': '#666666', 'font_size': 9})
        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#714B67', 'font_color': '#ffffff',
            'border': 1, 'valign': 'vcenter', 'text_wrap': True,
        })
        fmt_text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_num = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0.00'})
        fmt_int = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0'})
        fmt_pct = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '0.0"%"'})
        fmt_total_label = workbook.add_format({'bold': True, 'border': 1, 'bg_color': '#e9ecef'})
        fmt_total_num = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#e9ecef', 'num_format': '#,##0.00',
        })
        fmt_detail_head = workbook.add_format({
            'italic': True, 'bg_color': '#f1f1f1', 'font_color': '#495057',
            'border': 1, 'font_size': 8,
        })
        fmt_project_text = workbook.add_format({
            'bold': True, 'bg_color': '#f4f4f6', 'border': 1, 'font_size': 9,
        })
        fmt_project_num = workbook.add_format({
            'bold': True, 'bg_color': '#f4f4f6', 'border': 1, 'font_size': 9, 'num_format': '#,##0.00',
        })
        fmt_detail_text = workbook.add_format({'bg_color': '#fbfbfc', 'border': 1, 'font_size': 9})
        fmt_detail_num = workbook.add_format({
            'bg_color': '#fbfbfc', 'border': 1, 'font_size': 9, 'num_format': '#,##0.00',
        })

        sheet.write(0, 0, title, fmt_title)
        meta = f"Exported {datetime.now().strftime('%d-%b-%Y %H:%M')} by {request.env.user.name}"
        if subtitle:
            meta = f"{subtitle}  |  {meta}"
        sheet.write(1, 0, meta, fmt_meta)
        sheet.write(2, 0, "Click the + / - controls on the left to expand each employee's task, project & hours detail.", fmt_meta)

        header_row = 4
        for c, col in enumerate(columns):
            sheet.write(header_row, c, col.get('label', col.get('name')), fmt_header)
            width = max(12, len(str(col.get('label', ''))) + 4)
            sheet.set_column(c, c, min(width, 34))
        sheet.freeze_panes(header_row + 1, 0)

        def write_summary_row(r, values):
            for c, col in enumerate(columns):
                name = col.get('name')
                ctype = col.get('type')
                value = values.get(name)
                if ctype == 'monetary' or ctype == 'float':
                    sheet.write_number(r, c, float(value) if value else 0.0, fmt_num)
                elif ctype == 'percent':
                    sheet.write_number(r, c, float(value) if value else 0.0, fmt_pct)
                elif ctype == 'integer':
                    sheet.write_number(r, c, int(value) if value else 0, fmt_int)
                else:
                    sheet.write(r, c, '' if value in (None, False) else str(value), fmt_text)

        r = header_row + 1
        totals = {}
        for group in groups:
            summary = group.get('summary') or {}
            # detail = {
            #   delivery: [{project, hours, weighted, amount,
            #               tasks: [{task, hours, weighted, amount}]}, ...],
            #   sales:    [{ref, date, customer, amount}, ...],
            # } — mirrors the on-screen inline breakdown: a two-level
            # outline (Project under the employee, Task under its Project),
            # plus a flat Sales section, both collapsed under the employee.
            detail = group.get('detail') or {}
            delivery = detail.get('delivery') or []
            sales = detail.get('sales') or []

            write_summary_row(r, summary)
            for col in columns:
                if col.get('agg'):
                    totals[col['name']] = totals.get(col['name'], 0) + (float(summary.get(col['name']) or 0))
            r += 1

            if delivery:
                sheet.write(r, 0, '', fmt_detail_head)
                sheet.write(r, 1, 'Project', fmt_detail_head)
                sheet.write(r, 2, 'Task', fmt_detail_head)
                sheet.write(r, 3, 'Hours', fmt_detail_head)
                sheet.write(r, 4, 'Weighted', fmt_detail_head)
                sheet.write(r, 5, 'Revenue', fmt_detail_head)
                sheet.set_row(r, None, None, {'level': 1, 'hidden': True})
                r += 1

                for proj in delivery:
                    sheet.write(r, 1, proj.get('project') or '', fmt_project_text)
                    sheet.write_number(r, 3, float(proj.get('hours') or 0), fmt_project_num)
                    sheet.write_number(r, 4, float(proj.get('weighted') or 0), fmt_project_num)
                    sheet.write_number(r, 5, float(proj.get('amount') or 0), fmt_project_num)
                    sheet.set_row(r, None, None, {'level': 1, 'hidden': True, 'collapsed': True})
                    r += 1

                    for t in proj.get('tasks') or []:
                        sheet.write(r, 2, t.get('task') or '', fmt_detail_text)
                        sheet.write_number(r, 3, float(t.get('hours') or 0), fmt_detail_num)
                        sheet.write_number(r, 4, float(t.get('weighted') or 0), fmt_detail_num)
                        sheet.write_number(r, 5, float(t.get('amount') or 0), fmt_detail_num)
                        sheet.set_row(r, None, None, {'level': 2, 'hidden': True})
                        r += 1

            if sales:
                sheet.write(r, 0, '', fmt_detail_head)
                sheet.write(r, 1, 'Sale Order', fmt_detail_head)
                sheet.write(r, 2, 'Date', fmt_detail_head)
                sheet.write(r, 3, 'Customer', fmt_detail_head)
                sheet.write(r, 5, 'Amount', fmt_detail_head)
                sheet.set_row(r, None, None, {'level': 1, 'hidden': True})
                r += 1

                for s in sales:
                    sheet.write(r, 1, s.get('ref') or '', fmt_detail_text)
                    sheet.write(r, 2, s.get('date') or '', fmt_detail_text)
                    sheet.write(r, 3, s.get('customer') or '', fmt_detail_text)
                    sheet.write_number(r, 5, float(s.get('amount') or 0), fmt_detail_num)
                    sheet.set_row(r, None, None, {'level': 1, 'hidden': True})
                    r += 1

        if groups:
            for c, col in enumerate(columns):
                if c == 0:
                    sheet.write(r, c, 'Total', fmt_total_label)
                elif col.get('agg') and col.get('name') in totals:
                    sheet.write_number(r, c, totals[col['name']], fmt_total_num)
                else:
                    sheet.write(r, c, '', fmt_total_label)
            r += 1

        if r > header_row + 1:
            sheet.autofilter(header_row, 0, r - 1, len(columns) - 1)

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
