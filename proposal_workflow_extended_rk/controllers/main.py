import io
import json
from datetime import datetime

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request, content_disposition


class EinvoicingDashboardExport(http.Controller):
    """Excel download for the eInvoicing / Other Services dashboard tables.

    The dashboard rows are assembled in the browser from data it already
    fetched through the ORM (so record rules were applied), which means this
    only formats what the user could already see. Access is limited to Sales
    Administrators, the same people who get the Export action on CRM lists.
    """

    @http.route('/proposal_workflow_extended_rk/export/dashboard_xlsx',
                type='http', auth='user', methods=['POST'], csrf=False)
    def export_dashboard_xlsx(self, **kw):
        import xlsxwriter

        user = request.env.user
        if not (user.has_group('sales_team.group_sale_manager') or user.has_group('base.group_system')):
            raise AccessError('Only Sales Administrators can export this dashboard.')

        payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
        title = (payload.get('title') or 'Dashboard').strip() or 'Dashboard'
        columns = payload.get('columns') or []
        rows = payload.get('rows') or []

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        header = workbook.add_format({
            'bold': True, 'bg_color': '#714B67', 'font_color': '#ffffff',
            'border': 1, 'valign': 'vcenter', 'text_wrap': True,
        })
        text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        num = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0.00'})

        sheet = workbook.add_worksheet(title[:31])
        for c, col in enumerate(columns):
            sheet.write(0, c, col.get('label', ''), header)
            sheet.set_column(c, c, min(max(14, len(col.get('label', '')) + 4), 34))
        for r, row in enumerate(rows, start=1):
            for c, col in enumerate(columns):
                value = row.get(col.get('name'))
                if col.get('type') == 'number':
                    sheet.write_number(r, c, float(value or 0), num)
                else:
                    sheet.write(r, c, '' if value in (None, False) else str(value), text)
        sheet.freeze_panes(1, 0)
        if rows:
            sheet.autofilter(0, 0, len(rows), max(len(columns) - 1, 0))
        workbook.close()

        filename = f"{title.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return request.make_response(output.getvalue(), headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(filename)),
        ])
