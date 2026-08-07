import io
import json
from datetime import datetime

from odoo import http
from odoo.http import request, content_disposition

NUMERIC_TYPES = ('monetary', 'float', 'integer', 'percent')


def _cell_text(col, value):
    """Plain display text for a cell, used by the PDF/HTML export."""
    ctype = col.get('type')
    if value in (None, False, ''):
        if ctype == 'boolean':
            return 'No'
        return ''
    if ctype == 'boolean':
        return 'Yes' if value else 'No'
    if ctype in ('monetary', 'float'):
        return f"{float(value):,.2f}"
    if ctype == 'percent':
        return f"{float(value):,.1f}%"
    if ctype == 'integer':
        return f"{int(value):,}"
    return str(value)


def _table_html(title, subtitle, columns, rows, totals):
    thead = ''.join(
        f'<th class="{"num" if c.get("type") in NUMERIC_TYPES else ""}">{c.get("label", "")}</th>'
        for c in columns
    )
    body_rows = []
    for row in rows:
        cells = ''.join(
            f'<td class="{"num" if c.get("type") in NUMERIC_TYPES else ""}">'
            f'{_cell_text(c, row.get(c.get("name")))}</td>'
            for c in columns
        )
        body_rows.append(f'<tr>{cells}</tr>')

    total_row = ''
    if rows and totals:
        cells = []
        for i, c in enumerate(columns):
            if i == 0:
                cells.append('<td><strong>Total</strong></td>')
            elif c.get('agg') and c.get('name') in totals:
                cells.append(f'<td class="num"><strong>{_cell_text(c, totals[c["name"]])}</strong></td>')
            else:
                cells.append('<td></td>')
        total_row = f'<tr class="total">{"".join(cells)}</tr>'

    subtitle_html = f'<div class="meta">{subtitle}</div>' if subtitle else ''
    return f"""
        <h1>{title}</h1>
        {subtitle_html}
        <table>
            <thead><tr>{thead}</tr></thead>
            <tbody>{''.join(body_rows)}{total_row}</tbody>
        </table>
    """


class MisReportExportController(http.Controller):
    """Export the currently displayed (filtered / selected) MIS report rows,
    exactly as built client-side by MisReportView, to Excel or PDF.

    The controller performs no DB queries of its own: `rows` (and the
    optional `detail` block — the per-task timesheet breakdown) are field
    values the browser already fetched through the ORM (and therefore
    already passed record rules / access rights), so it only formats data
    the current user was already allowed to see.
    """

    def _read_payload(self):
        raw = request.httprequest.get_data(as_text=True)
        payload = json.loads(raw or '{}')
        title = (payload.get('title') or 'Report').strip() or 'Report'
        subtitle = payload.get('subtitle') or ''
        columns = payload.get('columns') or []
        rows = payload.get('rows') or []
        totals = payload.get('totals') or {}
        detail = payload.get('detail') or None
        return title, subtitle, columns, rows, totals, detail

    def _write_xlsx_sheet(self, workbook, formats, title, subtitle, columns, rows, totals):
        sheet = workbook.add_worksheet((title or 'Report')[:31])

        sheet.write(0, 0, title, formats['title'])
        meta = f"Exported {datetime.now().strftime('%d-%b-%Y %H:%M')} by {request.env.user.name}"
        if subtitle:
            meta = f"{subtitle}  |  {meta}"
        sheet.write(1, 0, meta, formats['meta'])

        header_row = 3
        for c, col in enumerate(columns):
            sheet.write(header_row, c, col.get('label', col.get('name')), formats['header'])
            width = max(12, len(str(col.get('label', ''))) + 4)
            sheet.set_column(c, c, min(width, 40))
        sheet.freeze_panes(header_row + 1, 0)

        r = header_row + 1
        for row in rows:
            for c, col in enumerate(columns):
                name = col.get('name')
                ctype = col.get('type')
                value = row.get(name)
                if ctype in ('monetary', 'float'):
                    sheet.write_number(r, c, float(value) if value else 0.0, formats['num'])
                elif ctype == 'percent':
                    sheet.write_number(r, c, float(value) if value else 0.0, formats['pct'])
                elif ctype == 'integer':
                    sheet.write_number(r, c, int(value) if value else 0, formats['int'])
                elif ctype == 'boolean':
                    sheet.write(r, c, 'Yes' if value else 'No', formats['text'])
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

    @http.route('/mis_report_kgrn/export/xlsx', type='http', auth='user', methods=['POST'], csrf=False)
    def export_xlsx(self, **kw):
        import xlsxwriter

        title, subtitle, columns, rows, totals, detail = self._read_payload()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        formats = {
            'title': workbook.add_format({'bold': True, 'font_size': 14}),
            'meta': workbook.add_format({'italic': True, 'font_color': '#666666', 'font_size': 9}),
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

        self._write_xlsx_sheet(workbook, formats, title, subtitle, columns, rows, totals)
        if detail and detail.get('rows'):
            self._write_xlsx_sheet(
                workbook, formats,
                detail.get('title') or 'Detail', detail.get('subtitle') or '',
                detail.get('columns') or [], detail.get('rows') or [], detail.get('totals') or {},
            )

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

    @http.route('/mis_report_kgrn/export/pdf', type='http', auth='user', methods=['POST'], csrf=False)
    def export_pdf(self, **kw):
        title, subtitle, columns, rows, totals, detail = self._read_payload()

        sections = [_table_html(title, subtitle, columns, rows, totals)]
        if detail and detail.get('rows'):
            sections.append(
                '<div class="page-break"></div>' +
                _table_html(
                    detail.get('title') or 'Detail', detail.get('subtitle') or '',
                    detail.get('columns') or [], detail.get('rows') or [], detail.get('totals') or {},
                )
            )

        html = f"""
        <html>
        <head>
        <style>
            @page {{ margin: 12mm; }}
            body {{ font-family: Arial, Helvetica, sans-serif; font-size: 9px; color: #212529; }}
            h1 {{ font-size: 16px; margin: 0 0 2px 0; }}
            .meta {{ font-size: 8px; color: #666; margin-bottom: 10px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ border: 1px solid #ced4da; padding: 3px 5px; text-align: left; }}
            th {{ background: #714B67; color: #fff; }}
            td.num, th.num {{ text-align: right; }}
            tr.total td {{ background: #e9ecef; }}
            tr:nth-child(even) td {{ background: #f8f9fa; }}
            .page-break {{ page-break-before: always; }}
        </style>
        </head>
        <body>
            {''.join(sections)}
        </body>
        </html>
        """

        pdf_content = request.env['ir.actions.report'].sudo()._run_wkhtmltopdf(
            [html], landscape=True,
        )
        filename = f"{title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )
