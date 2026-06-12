# -*- coding: utf-8 -*-
import json
from odoo import http
from odoo.http import content_disposition, request
from odoo.tools import html_escape


class LedgerXlsxController(http.Controller):
    """Streams the xlsx ledger reports generated server side."""

    @http.route('/ledger_xlsx_report', type='http', auth='user',
                methods=['POST'], csrf=False)
    def get_ledger_xlsx(self, model, data, report_name, **kw):
        uid = request.session.uid
        report_obj = request.env[model].with_user(uid)
        try:
            response = request.make_response(
                None,
                headers=[
                    ('Content-Type', 'application/vnd.ms-excel'),
                    ('Content-Disposition',
                     content_disposition(report_name + '.xlsx')),
                ],
            )
            report_obj.get_xlsx_report(json.loads(data), response)
            response.set_cookie('fileToken', 'dummy-token')
            return response
        except Exception as e:
            se = http.serialize_exception(e)
            error = {'code': 200, 'message': 'Odoo Server Error', 'data': se}
            return request.make_response(html_escape(json.dumps(error)))
