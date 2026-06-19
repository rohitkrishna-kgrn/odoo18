import json
import logging
import os

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ReferralPortalAPI(http.Controller):

    @http.route('/referral', type='http', auth='public', methods=['GET'], csrf=False)
    def referral_portal_page(self, **kwargs):
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html_path = os.path.join(module_dir, 'static', 'portal', 'referral_portal.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return request.make_response(content, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
        ])

    @http.route(
        '/kgrn/api/referral',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def create_referral_lead(self, **kwargs):

        try:
            data = json.loads(request.httprequest.data)
        except (json.JSONDecodeError, ValueError):
            return request.make_json_response(
                {'error': 'Invalid JSON payload'}, status=400
            )

        referrer_data = data.get('referrer', {})
        referral_data = data.get('referral', {})
        services = referral_data.get('services', [])

        if not referrer_data.get('email') or not referral_data.get('name'):
            return request.make_json_response(
                {'error': 'Missing required fields: referrer.email or referral.name'},
                status=422,
            )

        # Find or create referrer by email (case-insensitive)
        referrer_email = referrer_data.get('email', '').strip().lower()
        referrer = request.env['referral.referrer'].sudo().search(
            [('email', '=ilike', referrer_email)], limit=1
        )
        if not referrer:
            referrer = request.env['referral.referrer'].sudo().create({
                'name': referrer_data.get('name', ''),
                'company': referrer_data.get('company', ''),
                'email': referrer_email,
                'phone': referrer_data.get('phone', ''),
            })

        # Resolve CRM tags from service names
        tag_ids = []
        for svc in services:
            tag = request.env['crm.tag'].sudo().search([('name', '=', svc)], limit=1)
            if tag:
                tag_ids.append(tag.id)

        # Find the first non-converted, non-lost stage by sequence (= "New")
        new_stage = request.env['crm.stage'].sudo().search(
            [
                ('x_is_referral_converted', '=', False),
                ('x_is_referral_lost', '=', False),
            ],
            order='sequence asc',
            limit=1,
        )

        description = (
            f"<b>Referred by:</b> {referrer_data.get('name', '')} "
            f"({referrer_data.get('company', '')})<br/>"
            f"<b>Referrer Email:</b> {referrer_data.get('email', '')}<br/>"
            f"<b>Referrer Phone:</b> {referrer_data.get('phone', '')}<br/>"
            f"<b>Services of Interest:</b> "
            f"{', '.join(services) if services else 'Not specified'}"
        )

        lead_name = (
            f"Referral – {referral_data.get('name', '')} "
            f"({referral_data.get('company', '')})"
        )
        lead_vals = {
            'name': lead_name,
            'partner_name': referral_data.get('name', ''),
            'x_referral_company': referral_data.get('company', ''),
            'email_from': referral_data.get('email', ''),
            'phone': referral_data.get('phone', ''),
            'description': description,
            'x_referrer_id': referrer.id,
            'x_referral_ref': data.get('ref', ''),
            'x_is_referral': True,
            'tag_ids': [(6, 0, tag_ids)],
            'type': 'lead',
        }
        if new_stage:
            lead_vals['stage_id'] = new_stage.id

        try:
            lead = request.env['crm.lead'].sudo().create(lead_vals)
        except Exception:
            _logger.exception('Failed to create referral lead from portal')
            return request.make_json_response(
                {'error': 'Internal error creating lead'}, status=500
            )

        _logger.info(
            'Referral lead created: id=%s ref=%s referrer=%s',
            lead.id, lead.x_referral_ref, referrer.name,
        )
        return request.make_json_response({
            'id': lead.id,
            'ref': lead.x_referral_ref,
            'status': 'created',
        })
