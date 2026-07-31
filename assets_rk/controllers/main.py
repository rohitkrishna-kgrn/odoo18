import base64
import io
import re
import zipfile

from odoo import http
from odoo.http import request


def _safe_filename(name):
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', name or 'file').strip('_') or 'file'


class ITDocumentController(http.Controller):

    @http.route('/it_document/folder/<int:folder_id>/zip', type='http', auth='user')
    def download_folder_zip(self, folder_id, **kwargs):
        folder = request.env['it.document.folder'].browse(folder_id).exists()
        if not folder:
            return request.not_found()

        buffer = io.BytesIO()
        used_names = set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for doc in folder.document_ids.with_context(bin_size=False):
                if not doc.datas:
                    continue
                filename = _safe_filename(doc.file_name or doc.name)
                if filename in used_names:
                    stem, _, ext = filename.rpartition('.')
                    filename = f'{stem or filename}_{doc.id}.{ext}' if ext else f'{filename}_{doc.id}'
                used_names.add(filename)
                archive.writestr(filename, base64.b64decode(doc.datas))

        zip_name = _safe_filename(folder.name) + '.zip'
        return request.make_response(
            buffer.getvalue(),
            headers=[
                ('Content-Type', 'application/zip'),
                ('Content-Disposition', f'attachment; filename="{zip_name}"'),
            ],
        )
