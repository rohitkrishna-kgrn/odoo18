import json
import logging

from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class WebLeadWebhook(http.Controller):

    @http.route(
        '/webhook/web-lead',
        type='json',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def receive_web_lead(self, **kwargs):
        try:
            body_bytes = request.httprequest.get_data(as_text=True)
            data = json.loads(body_bytes) if body_bytes else {}
        except (json.JSONDecodeError, Exception):
            data = kwargs or {}

        name = data.get('name', '').strip()
        if not name:
            return {'success': False, 'error': 'name is required'}

        contact_number = data.get('contact_number') or data.get('phone') or ''
        email = data.get('email', '')
        body = data.get('body') or data.get('message') or ''
        service = data.get('service', '')

        # Collect any extra keys as form_data
        known = {'name', 'contact_number', 'phone', 'email', 'body', 'message', 'service'}
        extra = {k: v for k, v in data.items() if k not in known}
        form_data = json.dumps(extra, indent=2) if extra else ''

        vals = {
            'name': name,
            'contact_number': contact_number,
            'email': email,
            'body': body,
            'service': service,
            'form_data': form_data,
            'state': 'new',
        }

        lead = request.env['crm.web.lead'].sudo().create(vals)
        _logger.info('Web lead created via webhook: id=%s name=%s', lead.id, lead.name)

        return {
            'success': True,
            'id': lead.id,
            'name': lead.name,
        }
