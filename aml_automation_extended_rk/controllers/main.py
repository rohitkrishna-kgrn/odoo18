import json
import base64
import logging
from datetime import timedelta

from markupsafe import Markup
from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class AmlPortalController(http.Controller):

    def _attachment_token(self, attachment):
        """Return a per-attachment access token so anonymous portal visitors can
        download their own files via /web/content/<id>?access_token=... without
        the attachment needing to be globally public (which would let anyone
        who guesses an ID download another client's KYC documents)."""
        if not attachment.access_token:
            attachment.generate_access_token()
        return attachment.access_token

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

        # Attachments previously uploaded for director / shareholder rows are
        # tagged with (line_type, line_index, doc_type) so they can be
        # re-attached to the right row + slot after a page refresh, without
        # requiring the user to re-upload.
        def _uploaded_docs_by_index(line_type):
            attachments = request.env['ir.attachment'].sudo().search([
                ('res_model', '=', 'aml.request'),
                ('res_id', '=', aml.id),
                ('aml_line_type', '=', line_type),
            ], order='id desc')
            by_index = {}
            for a in attachments:
                slot = by_index.setdefault(a.aml_line_index, {})
                if a.aml_doc_type not in slot:
                    slot[a.aml_doc_type] = {
                        'attachment_id': a.id,
                        'filename': a.name.rsplit(' - ', 1)[-1],
                    }
            return by_index

        dir_uploaded_docs = _uploaded_docs_by_index('director')
        sh_uploaded_docs = _uploaded_docs_by_index('shareholder')

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
            'uploaded_docs': dir_uploaded_docs.get(idx, {}),
        } for idx, d in enumerate(aml.director_line_ids, start=1)]

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
            'uploaded_docs': sh_uploaded_docs.get(idx, {}),
        } for idx, s in enumerate(aml.shareholder_line_ids, start=1)]

        doc_lines = [{
            'id': d.id,
            'doc_key': d.doc_key,
            'doc_name': d.doc_name,
            'is_mandatory': d.is_mandatory,
            'tooltip': d.tooltip or '',
            'has_attachment': bool(d.attachment_ids),
            'attachments': [
                {'id': a.id, 'name': a.name, 'token': self._attachment_token(a)}
                for a in d.attachment_ids
            ],
        } for d in aml.document_line_ids]

        def s(v): return v or ''
        def d(v): return str(v) if v else ''

        saved_fields = {
            # Entity
            'ent_entity_name': s(aml.ent_entity_name),
            'ent_legal_type': s(aml.ent_legal_type),
            'ent_trading_name': s(aml.ent_trading_name),
            'ent_date_of_incorporation': d(aml.ent_date_of_incorporation),
            'ent_place_of_incorporation': s(aml.ent_place_of_incorporation),
            'ent_registration_authority': s(aml.ent_registration_authority),
            'ent_license_number': s(aml.ent_license_number),
            'ent_license_expiry': d(aml.ent_license_expiry),
            'ent_registered_address': s(aml.ent_registered_address),
            'ent_business_address': s(aml.ent_business_address),
            'ent_industry_type': s(aml.ent_industry_type),
            'ent_nature_of_business': s(aml.ent_nature_of_business),
            'ent_source_of_wealth': s(aml.ent_source_of_wealth),
            'ent_ownership_complexity': s(aml.ent_ownership_complexity),
            'ent_countries_commercial': s(aml.ent_countries_commercial),
            'ent_high_risk_jurisdiction': s(aml.ent_high_risk_jurisdiction),
            'ent_channel_cash': aml.ent_channel_cash,
            'ent_channel_wire': aml.ent_channel_wire,
            'ent_channel_cheque': aml.ent_channel_cheque,
            'ent_channel_credit': aml.ent_channel_credit,
            'ent_channel_crypto': aml.ent_channel_crypto,
            'ent_channel_debit': aml.ent_channel_debit,
            'ent_cash_less_50k': aml.ent_cash_less_50k,
            'ent_cash_more_50k': aml.ent_cash_more_50k,
            'ent_cash_na': aml.ent_cash_na,
            'ent_top5_suppliers': s(aml.ent_top5_suppliers),
            'ent_top5_customers': s(aml.ent_top5_customers),
            'ent_contact_name': s(aml.ent_contact_name),
            'ent_contact_designation': s(aml.ent_contact_designation),
            'ent_contact_email': s(aml.ent_contact_email),
            'ent_contact_mobile': s(aml.ent_contact_mobile),
            'ent_manager_name': s(aml.ent_manager_name),
            'ent_parent_company_name': s(aml.ent_parent_company_name),
            'ent_parent_company_address': s(aml.ent_parent_company_address),
            'ent_international_sanctions': s(aml.ent_international_sanctions),
            'ent_pep_shareholder': s(aml.ent_pep_shareholder),
            'ent_pep_director': s(aml.ent_pep_director),
            'ent_pep_owner': s(aml.ent_pep_owner),
            'ent_pep_local_sponsor': s(aml.ent_pep_local_sponsor),
            'ent_pep_key_management': s(aml.ent_pep_key_management),
            'ent_pep_officer': s(aml.ent_pep_officer),
            'ent_pep_agent': s(aml.ent_pep_agent),
            # Individual
            'ind_full_name': s(aml.ind_full_name),
            'ind_gender': s(aml.ind_gender),
            'ind_nationality': s(aml.ind_nationality),
            'ind_date_of_birth': d(aml.ind_date_of_birth),
            'ind_place_of_birth': s(aml.ind_place_of_birth),
            'ind_id_type': s(aml.ind_id_type),
            'ind_id_type_other': s(aml.ind_id_type_other),
            'ind_id_number': s(aml.ind_id_number),
            'ind_issuing_country': s(aml.ind_issuing_country),
            'ind_valid_until': d(aml.ind_valid_until),
            'ind_permanent_address': s(aml.ind_permanent_address),
            'ind_uae_address': s(aml.ind_uae_address),
            'ind_city': s(aml.ind_city),
            'ind_country': s(aml.ind_country),
            'ind_mobile': s(aml.ind_mobile),
            'ind_email': s(aml.ind_email),
            'ind_proof_address_type': s(aml.ind_proof_address_type),
            'ind_proof_address_other': s(aml.ind_proof_address_other),
            'ind_document_date': d(aml.ind_document_date),
            'ind_emirates_id_attached': s(aml.ind_emirates_id_attached),
            'ind_passport_attached': s(aml.ind_passport_attached),
            'ind_proof_address_attached': s(aml.ind_proof_address_attached),
            'ind_other_id_attached': s(aml.ind_other_id_attached),
            'ind_verified_portal': s(aml.ind_verified_portal),
            'ind_verified_physically': s(aml.ind_verified_physically),
            'ind_video_kyc': s(aml.ind_video_kyc),
            'ind_purpose_of_relationship': s(aml.ind_purpose_of_relationship),
            'ind_purpose_of_relationship_other': s(aml.ind_purpose_of_relationship_other),
            'ind_expected_transactions': s(aml.ind_expected_transactions),
            'ind_monthly_turnover': s(aml.ind_monthly_turnover),
            'ind_source_of_funds': s(aml.ind_source_of_funds),
            'ind_hold_shares_behalf': s(aml.ind_hold_shares_behalf),
            'ind_high_risk_jurisdiction': s(aml.ind_high_risk_jurisdiction),
            'ind_anticipated_origin': s(aml.ind_anticipated_origin),
            'ind_dual_citizenship': s(aml.ind_dual_citizenship),
            'ind_dual_citizenship_detail': s(aml.ind_dual_citizenship_detail),
            'ind_high_net_worth': s(aml.ind_high_net_worth),
            'ind_bank_name': s(aml.ind_bank_name),
            'ind_bank_branch_address': s(aml.ind_bank_branch_address),
            'ind_iban': s(aml.ind_iban),
            # UBO
            'ubo_full_name': s(aml.ubo_full_name),
            'ubo_gender': s(aml.ubo_gender),
            'ubo_nationality': s(aml.ubo_nationality),
            'ubo_date_of_birth': d(aml.ubo_date_of_birth),
            'ubo_place_of_birth': s(aml.ubo_place_of_birth),
            'ubo_dual_citizenship': s(aml.ubo_dual_citizenship),
            'ubo_dual_citizenship_detail': s(aml.ubo_dual_citizenship_detail),
            'ubo_source_of_income': s(aml.ubo_source_of_income),
            'ubo_hold_shares_behalf': s(aml.ubo_hold_shares_behalf),
            'ubo_high_risk_jurisdiction': s(aml.ubo_high_risk_jurisdiction),
            'ubo_home_country_address': s(aml.ubo_home_country_address),
            'ubo_uae_address': s(aml.ubo_uae_address),
            'ubo_mobile': s(aml.ubo_mobile),
            'ubo_email': s(aml.ubo_email),
            'ubo_high_net_worth': s(aml.ubo_high_net_worth),
            'ubo_bank_name': s(aml.ubo_bank_name),
            'ubo_bank_branch_address': s(aml.ubo_bank_branch_address),
            'ubo_iban': s(aml.ubo_iban),
            # Declaration dates
            'director_declaration_date': d(aml.director_declaration_date),
            'shareholder_declaration_date': d(aml.shareholder_declaration_date),
        }

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        logo_url = '%s/web/image/res.company/%s/logo' % (base_url, aml.company_id.id)
        return request.render('aml_automation_extended_rk.portal_kyc_form', {
            'aml': aml,
            'access_token': access_token,
            'logo_url': logo_url,
            'directors_json': Markup(json.dumps(directors)),
            'shareholders_json': Markup(json.dumps(shareholders)),
            'doc_lines_json': Markup(json.dumps(doc_lines)),
            'saved_fields_json': Markup(json.dumps(saved_fields)),
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
        file_token = attachment.generate_access_token()[0]
        doc_line.write({'attachment_ids': [(4, attachment.id)], 'is_submitted': True})
        return json.dumps({
            'success': True,
            'attachment_id': attachment.id,
            'filename': uploaded_file.filename,
            'file_token': file_token,
        })

    @http.route('/aml/form/upload_director_doc', type='http', auth='public', methods=['POST'], csrf=False)
    def upload_director_doc(self, access_token, dir_index=None, dir_name=None, doc_type=None, **post):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return json.dumps({'error': 'Invalid token'})

        uploaded_file = request.httprequest.files.get('file')
        if not uploaded_file:
            return json.dumps({'error': 'Missing file'})

        doc_type_labels = {
            'passport': 'Passport Copy/Emirates ID/any government issued identity with compulsory condition',
            'proof_of_residence': 'Proof of Residence (Utility Bill / Lease Agreement / Bank Statement) issued within the last 3 months showing the address of respective individuals',
        }
        doc_label = doc_type_labels.get(doc_type, doc_type or 'Document')
        name_prefix = 'Director %s - %s - %s' % (dir_index or '', dir_name or '', doc_label)

        try:
            line_index = int(dir_index or 0)
        except (ValueError, TypeError):
            line_index = 0

        # Replace any previous upload for this same row + doc slot instead of
        # leaving orphaned attachments behind.
        request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'aml.request'),
            ('res_id', '=', aml.id),
            ('aml_line_type', '=', 'director'),
            ('aml_line_index', '=', line_index),
            ('aml_doc_type', '=', doc_type),
        ]).unlink()

        attachment = request.env['ir.attachment'].sudo().create({
            'name': '%s - %s' % (name_prefix, uploaded_file.filename),
            'raw': uploaded_file.read(),
            'res_model': 'aml.request',
            'res_id': aml.id,
            'aml_line_type': 'director',
            'aml_line_index': line_index,
            'aml_doc_type': doc_type,
        })
        return json.dumps({
            'success': True,
            'attachment_id': attachment.id,
            'filename': uploaded_file.filename,
        })

    @http.route('/aml/form/upload_shareholder_doc', type='http', auth='public', methods=['POST'], csrf=False)
    def upload_shareholder_doc(self, access_token, sh_index=None, sh_name=None, doc_type=None, **post):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return json.dumps({'error': 'Invalid token'})

        uploaded_file = request.httprequest.files.get('file')
        if not uploaded_file:
            return json.dumps({'error': 'Missing file'})

        doc_type_labels = {
            'passport': 'Passport Copy/Emirates ID/any government issued identity with compulsory condition',
            'proof_of_residence': 'Proof of Residence (Utility Bill / Lease Agreement / Bank Statement) issued within the last 3 months showing the address of respective individuals',
            'trade_license': 'Trade License/Certificate of Incorporation',
            'memorandum': 'Memorandum of Association / Articles of Association',
        }
        doc_label = doc_type_labels.get(doc_type, doc_type or 'Document')
        name_prefix = 'Shareholder %s - %s - %s' % (sh_index or '', sh_name or '', doc_label)

        try:
            line_index = int(sh_index or 0)
        except (ValueError, TypeError):
            line_index = 0

        # Replace any previous upload for this same row + doc slot instead of
        # leaving orphaned attachments behind.
        request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'aml.request'),
            ('res_id', '=', aml.id),
            ('aml_line_type', '=', 'shareholder'),
            ('aml_line_index', '=', line_index),
            ('aml_doc_type', '=', doc_type),
        ]).unlink()

        attachment = request.env['ir.attachment'].sudo().create({
            'name': '%s - %s' % (name_prefix, uploaded_file.filename),
            'raw': uploaded_file.read(),
            'res_model': 'aml.request',
            'res_id': aml.id,
            'aml_line_type': 'shareholder',
            'aml_line_index': line_index,
            'aml_doc_type': doc_type,
        })
        return json.dumps({
            'success': True,
            'attachment_id': attachment.id,
            'filename': uploaded_file.filename,
        })

    @http.route('/aml/form/remove_attachment', type='json', auth='public', csrf=False)
    def remove_attachment(self, access_token, attachment_id, doc_line_id=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('access_token', '=', access_token), ('state', '=', 'draft')
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        try:
            attachment_id = int(attachment_id)
        except (ValueError, TypeError):
            return {'error': 'Invalid attachment_id'}

        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not attachment.exists():
            return {'error': 'Attachment not found'}

        # Attachments uploaded through this form live under two different
        # ownership patterns depending on where they were uploaded:
        #  - Director/Shareholder doc slots -> res_model='aml.request', res_id=aml.id
        #  - Main "Documents" checklist rows -> res_model='aml.request.document', res_id=<line id>
        # Verify the attachment actually belongs to this draft request before deleting it.
        if attachment.res_model == 'aml.request' and attachment.res_id == aml.id:
            pass
        elif attachment.res_model == 'aml.request.document':
            doc_line = request.env['aml.request.document'].sudo().browse(attachment.res_id)
            if not doc_line.exists() or doc_line.request_id.id != aml.id:
                return {'error': 'Attachment not found'}
            doc_line.write({'attachment_ids': [(3, attachment.id)]})
            if not doc_line.attachment_ids:
                doc_line.write({'is_submitted': False})
        else:
            return {'error': 'Attachment not found'}

        attachment.unlink()
        return {'success': True}

    @http.route('/aml/form/submit', type='json', auth='public', csrf=False)
    def submit_form(self, access_token, signatory_name=None, signatory_designation=None,
                    signed_on=None, signature_data=None, **kwargs):
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
            'signatory_designation': signatory_designation or '',
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
            ('state', 'in', ('hit_detected', 'in_progress')),
        ], limit=1)
        if not aml:
            return request.render('aml_automation_extended_rk.portal_form_expired', {})

        hit_docs = [{
            'id': d.id,
            'document_name': d.document_name,
            'staff_note': d.staff_note or '',
            'client_note': d.client_note or '',
            'submitted': d.submitted,
            'attachments': [
                {'id': a.id, 'name': a.name, 'token': self._attachment_token(a)}
                for a in d.attachment_ids
            ],
            'reference_file': {
                'id': d.staff_sample_attachment_id.id,
                'name': d.staff_sample_attachment_id.name,
                'token': self._attachment_token(d.staff_sample_attachment_id),
            } if d.staff_sample_attachment_id else None,
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
            ('state', 'in', ('hit_detected', 'in_progress')),
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
        file_token = attachment.generate_access_token()[0]
        hit_doc.write({'attachment_ids': [(4, attachment.id)], 'submitted': True})
        return json.dumps({
            'success': True,
            'attachment_id': attachment.id,
            'filename': uploaded_file.filename,
            'file_token': file_token,
        })

    @http.route('/aml/additional/remove_doc', type='json', auth='public', csrf=False)
    def remove_additional_doc(self, additional_token, attachment_id, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', 'in', ('hit_detected', 'in_progress')),
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        try:
            attachment_id = int(attachment_id)
        except (ValueError, TypeError):
            return {'error': 'Invalid attachment_id'}

        attachment = request.env['ir.attachment'].sudo().browse(attachment_id)
        if not attachment.exists() or attachment.res_model != 'aml.hit.document':
            return {'error': 'Attachment not found'}

        hit_doc = request.env['aml.hit.document'].sudo().browse(attachment.res_id)
        if not hit_doc.exists() or hit_doc.request_id.id != aml.id:
            return {'error': 'Attachment not found'}

        hit_doc.write({'attachment_ids': [(3, attachment.id)]})
        attachment.unlink()
        if not hit_doc.attachment_ids:
            hit_doc.write({'submitted': False})
        return {'success': True}

    @http.route('/aml/additional/save_note', type='json', auth='public', csrf=False)
    def save_additional_note(self, additional_token, hit_doc_id, note='', **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', 'in', ('hit_detected', 'in_progress')),
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        try:
            hit_doc_id = int(hit_doc_id)
        except (ValueError, TypeError):
            return {'error': 'Invalid hit_doc_id'}

        hit_doc = request.env['aml.hit.document'].sudo().browse(hit_doc_id)
        if not hit_doc.exists() or hit_doc.request_id.id != aml.id:
            return {'error': 'Document not found'}

        hit_doc.write({'client_note': note or ''})
        return {'success': True}

    @http.route('/aml/additional/submit', type='json', auth='public', csrf=False)
    def submit_additional(self, additional_token, notes=None, **kwargs):
        aml = request.env['aml.request'].sudo().search([
            ('additional_access_token', '=', additional_token),
            ('state', 'in', ('hit_detected', 'in_progress')),
        ], limit=1)
        if not aml:
            return {'error': 'Invalid or expired token'}

        if aml.state == 'hit_detected':
            # Standard HIT flow: move to additional_info for manager review
            aml.write({
                'state': 'additional_info',
                'additional_info_enabled': True,
                'additional_info_text': notes or '',
                'additional_submitted_date': fields.Datetime.now(),
            })
            aml.message_post(body=_("Client submitted additional documents for HIT review."))
            aml._notify_aml_managers_and_assignee(
                subject=_("AML Request %s – Additional Info Received") % aml.name,
                intro=_("The client <strong>%s</strong> has submitted the requested additional documents. "
                        "Please review and take action (Approve / Reject).") % aml.partner_id.name,
                kv_rows=[
                    (_('Client'), aml.partner_id.name),
                    (_('AML Reference'), aml.name),
                ],
            )
        else:
            # In Progress flow: stay in_progress, just record receipt
            aml.write({
                'additional_info_enabled': True,
                'additional_info_text': notes or '',
                'additional_submitted_date': fields.Datetime.now(),
            })
            aml.message_post(
                body=_("Client submitted additional documents requested during investigation.")
            )
            aml._notify_aml_managers_and_assignee(
                subject=_("AML Request %s – Additional Documents Received") % aml.name,
                intro=_("The client <strong>%s</strong> has uploaded the additional documents requested "
                        "during the AML investigation. Please review them in the Additional Info tab.") % aml.partner_id.name,
                kv_rows=[
                    (_('Client'), aml.partner_id.name),
                    (_('AML Reference'), aml.name),
                ],
            )

        return {'success': True}

    # =========================================================================
    # Branded email logo (white-background JPEG, safe for every email client)
    # =========================================================================
    @http.route('/aml/logo/<int:company_id>.jpg', type='http', auth='public', csrf=False)
    def aml_email_logo(self, company_id, **kwargs):
        company = request.env['res.company'].sudo().browse(company_id)
        jpeg_b64 = company.exists() and request.env['aml.request'].sudo()._compute_logo_white_jpeg(company)
        if not jpeg_b64:
            return request.not_found()
        return request.make_response(
            base64.b64decode(jpeg_b64),
            headers=[('Content-Type', 'image/jpeg'), ('Cache-Control', 'public, max-age=86400')],
        )
