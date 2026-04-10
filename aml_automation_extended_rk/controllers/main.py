import json
import base64
import logging
from datetime import timedelta

from markupsafe import Markup
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmlPortalController(http.Controller):

    # =========================================================================
    # Main KYC Form (multi-page)
    # =========================================================================

    @http.route('/aml/form/<string:access_token>', type='http', auth='public', website=True)
    def aml_form(self, access_token, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token),
            ('state', '=', 'draft'),
        ], limit=1)
        if not aml:
            return request.render('aml_automation_extended_rk.portal_form_expired', {})

        # Pre-load existing director / shareholder lines for JS rendering
        directors = [{
            'id': d.id,
            'full_name': d.full_name,
            'position': d.position or '',
            'nationality': d.nationality or '',
            'id_passport_no': d.id_passport_no or '',
            'appointment_date': str(d.appointment_date) if d.appointment_date else '',
            'resignation_date': str(d.resignation_date) if d.resignation_date else '',
            'status': d.status or 'active',
        } for d in aml.director_line_ids]

        shareholders = [{
            'id': s.id,
            'shareholder_name': s.shareholder_name,
            'nationality': s.nationality or '',
            'shareholder_type': s.shareholder_type or '',
            'passport_no': s.passport_no or '',
            'share_class': s.share_class or '',
            'num_shares': s.num_shares or 0,
            'percentage_holding': s.percentage_holding or 0.0,
            'date_of_entry': str(s.date_of_entry) if s.date_of_entry else '',
        } for s in aml.shareholder_line_ids]

        doc_lines = [{
            'id': d.id,
            'doc_key': d.doc_key,
            'doc_name': d.doc_name,
            'is_mandatory': d.is_mandatory,
            'tooltip': d.tooltip or '',
            'has_attachment': bool(d.attachment_ids),
            'attachment_names': [a.name for a in d.attachment_ids],
        } for d in aml.document_line_ids]

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        logo_url = '%s/web/image/res.company/%s/logo' % (base_url, aml.company_id.id)
        return request.render('aml_automation_extended_rk.portal_kyc_form', {
            'aml': aml,
            'access_token': access_token,
            'logo_url': logo_url,
            'directors_json': Markup(json.dumps(directors)),
            'shareholders_json': Markup(json.dumps(shareholders)),
            'doc_lines_json': Markup(json.dumps(doc_lines)),
        })

    @http.route('/aml/form/save_page', type='json', auth='public', csrf=False)
    def save_page(self, access_token, page, data=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token),
            ('state', '=', 'draft'),
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}
        if data:
            allowed = aml.get_portal_fields_for_page(page)
            safe_data = {k: v for k, v in data.items() if k in allowed}
            if safe_data:
                aml.write(safe_data)
        return {'success': True}

    @http.route('/aml/form/save_directors', type='json', auth='public', csrf=False)
    def save_directors(self, access_token, directors=None, declaration_date=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return {'error': 'Invalid token'}

        aml.director_line_ids.unlink()
        if directors:
            for idx, d in enumerate(directors):
                request.env['aml.request.director'].sudo().create({
                    'request_id': aml.id,
                    'sequence': (idx + 1) * 10,
                    'full_name': d.get('full_name', ''),
                    'position': d.get('position', ''),
                    'nationality': d.get('nationality', ''),
                    'id_passport_no': d.get('id_passport_no', ''),
                    'appointment_date': d.get('appointment_date') or False,
                    'resignation_date': d.get('resignation_date') or False,
                    'status': d.get('status', 'active'),
                })
        if declaration_date:
            aml.write({'director_declaration_date': declaration_date})
        return {'success': True}

    @http.route('/aml/form/save_shareholders', type='json', auth='public', csrf=False)
    def save_shareholders(self, access_token, shareholders=None, declaration_date=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return {'error': 'Invalid token'}

        aml.shareholder_line_ids.unlink()
        if shareholders:
            for idx, s in enumerate(shareholders):
                request.env['aml.request.shareholder'].sudo().create({
                    'request_id': aml.id,
                    'sequence': (idx + 1) * 10,
                    'shareholder_name': s.get('shareholder_name', ''),
                    'nationality': s.get('nationality', ''),
                    'shareholder_type': s.get('shareholder_type', ''),
                    'passport_no': s.get('passport_no', ''),
                    'share_class': s.get('share_class', ''),
                    'num_shares': int(s.get('num_shares', 0) or 0),
                    'percentage_holding': float(s.get('percentage_holding', 0) or 0),
                    'date_of_entry': s.get('date_of_entry') or False,
                })
        if declaration_date:
            aml.write({'shareholder_declaration_date': declaration_date})
        return {'success': True}

    @http.route('/aml/form/upload_doc', type='http', auth='public', methods=['POST'], csrf=False)
    def upload_doc(self, access_token, doc_id=None, **post):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return json.dumps({'error': 'Invalid token'})

        uploaded_file = request.httprequest.files.get('file')
        if not uploaded_file or not doc_id:
            return json.dumps({'error': 'Missing file or doc_id'})

        try:
            doc_id = int(doc_id)
        except (ValueError, TypeError):
            return json.dumps({'error': 'Invalid doc_id'})

        doc_line = request.env['aml.request.document'].sudo().browse(doc_id)
        if not doc_line.exists() or doc_line.request_id.id != aml.id:
            return json.dumps({'error': 'Document line not found'})

        file_data = uploaded_file.read()
        attachment = request.env['ir.attachment'].sudo().create({
            'name': uploaded_file.filename,
            'raw': file_data,
            'res_model': 'aml.request.document',
            'res_id': doc_line.id,
        })
        doc_line.write({'attachment_ids': [(4, attachment.id)], 'is_submitted': True})
        return json.dumps({
            'success': True,
            'attachment_id': attachment.id,
            'filename': uploaded_file.filename,
        })

    @http.route('/aml/form/submit', type='json', auth='public', csrf=False)
    def submit_form(self, access_token, signatory_name=None, signature_data=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        # Assign sequence ID
        seq_name = request.env['ir.sequence'].sudo().next_by_code('aml.request') or 'AML000001'

        sig_binary = False
        if signature_data:
            try:
                # signature_data is a base64 data URL: "data:image/png;base64,..."
                sig_binary = signature_data.split(',', 1)[1].encode()
            except Exception:
                sig_binary = False

        now = fields.Datetime.now()
        aml.write({
            'name': seq_name,
            'state': 'new',
            'deadline': now + timedelta(hours=24),
            'signatory_name': signatory_name or '',
            'signature_data': sig_binary,
            'signed_date': now,
            'accept_declaration': True,
        })

        # Notify AML managers
        aml._notify_aml_managers_new_request()

        return {'success': True, 'aml_id': aml.name}

    # =========================================================================
    # Confirmation page after submission
    # =========================================================================

    @http.route('/aml/form/confirmed/<string:aml_name>', type='http', auth='public', website=True)
    def aml_confirmed(self, aml_name, **kwargs):
        return request.render('aml_automation_extended_rk.portal_form_confirmed', {
            'aml_name': aml_name,
        })

    # =========================================================================
    # Additional Info Form (HIT Detected flow)
    # =========================================================================

    @http.route('/aml/additional/<string:additional_token>', type='http', auth='public', website=True)
    def additional_form(self, additional_token, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', '=', 'hit_detected'),
        ], limit=1)
        if not aml:
            return request.render('aml_automation_extended_rk.portal_form_expired', {})

        hit_docs = [{
            'id': d.id,
            'document_name': d.document_name,
            'submitted': d.submitted,
        } for d in aml.hit_document_ids]

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        logo_url = '%s/web/image/res.company/%s/logo' % (base_url, aml.company_id.id)
        return request.render('aml_automation_extended_rk.portal_additional_form', {
            'aml': aml,
            'additional_token': additional_token,
            'logo_url': logo_url,
            'hit_docs_json': Markup(json.dumps(hit_docs)),
        })

    @http.route('/aml/additional/upload', type='http', auth='public', methods=['POST'], csrf=False)
    def upload_additional_doc(self, additional_token, hit_doc_id=None, **post):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', '=', 'hit_detected'),
        ], limit=1)
        if not aml:
            return json.dumps({'error': 'Invalid token'})

        uploaded_file = request.httprequest.files.get('file')
        if not uploaded_file or not hit_doc_id:
            return json.dumps({'error': 'Missing file or hit_doc_id'})

        try:
            hit_doc_id = int(hit_doc_id)
        except (ValueError, TypeError):
            return json.dumps({'error': 'Invalid hit_doc_id'})

        hit_doc = request.env['aml.hit.document'].sudo().browse(hit_doc_id)
        if not hit_doc.exists() or hit_doc.request_id.id != aml.id:
            return json.dumps({'error': 'Document not found'})

        attachment = request.env['ir.attachment'].sudo().create({
            'name': uploaded_file.filename,
            'raw': uploaded_file.read(),
            'res_model': 'aml.hit.document',
            'res_id': hit_doc.id,
        })
        hit_doc.write({'attachment_ids': [(4, attachment.id)], 'submitted': True})
        return json.dumps({'success': True, 'filename': uploaded_file.filename})

    @http.route('/aml/additional/submit', type='json', auth='public', csrf=False)
    def submit_additional(self, additional_token, notes=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', '=', 'hit_detected'),
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        aml.write({
            'state': 'additional_info',
            'additional_info_enabled': True,
            'additional_info_text': notes or '',
            'additional_submitted_date': fields.Datetime.now(),
        })
        aml.message_post(body=_("Client submitted additional documents for HIT review."))

        # Notify AML manager
        aml._notify_aml_managers_and_management(
            subject=_("AML Request %s – Additional Info Received") % aml.name,
            body=_(
                "<p>The client <strong>%s</strong> has submitted the requested additional documents "
                "for AML Request <strong>%s</strong>.</p>"
                "<p>Please review and take action (Approve / Reject).</p>"
            ) % (aml.partner_id.name, aml.name),
        )

        return {'success': True}
