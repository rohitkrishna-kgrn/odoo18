import io
import os
import zipfile

from odoo import fields, http
from odoo.http import content_disposition, request

from ..models.excel_export import EXPORT_COLUMNS


class HrDmsController(http.Controller):

    @http.route('/hr_dms/document/<int:doc_id>/download', type='http', auth='user')
    def download_document_files(self, doc_id, **kw):
        """Every file of a document in one zip. Same rule as a single file: the user must be able
        to read the document and the category must let them download; the download is logged."""
        doc = request.env['hr.dms.document'].browse(doc_id).exists()
        if not doc:
            raise request.not_found()
        doc.check_access('read')
        files = doc.sudo().attachment_ids
        if not files:
            raise request.not_found()
        doc._check_download(detail=', '.join(files.mapped('name')))
        buffer, used = io.BytesIO(), set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for att in files:
                base, ext = os.path.splitext(att.name or 'file')
                name, n = base + ext, 1
                while name.lower() in used:
                    n += 1
                    name = f"{base} ({n}){ext}"
                used.add(name.lower())
                archive.writestr(name, att.raw or b'')
        filename = f"{doc.name} - {doc.employee_id.sudo().name}.zip"
        return request.make_response(buffer.getvalue(), headers=[
            ('Content-Type', 'application/zip'),
            ('Content-Disposition', content_disposition(filename)),
        ])

    @http.route('/hr_dms/export/<string:model>', type='http', auth='user')
    def export_xlsx(self, model, ids='', **kw):
        """Configuration › Export: the selected records as an .xlsx, Administrator only, logged."""
        if model not in EXPORT_COLUMNS:
            raise request.not_found()
        exporter = request.env['hr.dms.excel.export']
        exporter._check_export_right()
        records = request.env[model].with_context(active_test=False).browse(
            [int(i) for i in ids.split(',') if i.strip().isdigit()]).exists()
        if not records:
            raise request.not_found()
        content = exporter._build_xlsx(records)
        label = request.env._("Employee Documents") if model == 'hr.dms.document' \
            else request.env._("Personal Details")
        request.env['hr.dms.audit.log'].log('export', request.env._(
            "%(what)s exported to Excel: %(count)s record(s) of %(employees)s employee(s)",
            what=label, count=len(records), employees=len(records.sudo().employee_id)),
            confidential=model == 'hr.dms.document' and any(records.sudo().mapped('confidential')))
        filename = f"{label} {fields.Date.context_today(records[:1]).strftime('%Y-%m-%d')}.xlsx"
        return request.make_response(content, headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', content_disposition(filename)),
        ])
