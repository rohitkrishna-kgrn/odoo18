import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Accepted category aliases → stored value.
_CATEGORY_ALIASES = {
    'qualified': 'qualified',
    'valid': 'qualified',
    'spam': 'spam',
    'irrelevant': 'spam',
    'spam/irrelevant': 'spam',
    'spam / irrelevant': 'spam',
    'technical': 'technical',
    'technical issue': 'technical',
    'error': 'technical',
    'processing error': 'technical',
    'unknown': 'technical',
}

# Incoming key → model field (incoming keys are lower-cased before lookup).
_FIELD_MAP = {
    'name': 'name',
    'email': 'email',
    'work email': 'email',
    'email_from': 'email',
    'phone': 'phone',
    'work phone': 'phone',
    'contact_number': 'phone',
    'company': 'company',
    'city': 'city',
    'company_size': 'company_size',
    'company size': 'company_size',
    'currently_uses_erp': 'currently_uses_erp',
    'currently uses erp': 'currently_uses_erp',
    'plans_to_implement': 'plans_to_implement',
    'plans to implement e-invoicing': 'plans_to_implement',
    'service_interest': 'service_interest',
    'service interest': 'service_interest',
    'source': 'source',
    'ai_reason': 'ai_reason',
    'ai reason': 'ai_reason',
    'reason': 'ai_reason',
    'detail': 'detail',
    'execution_id': 'execution_id',
    'execution id': 'execution_id',
}

_BOOL_FIELDS = {'validity_passed', 'service_relevant'}


def _to_bool(val):
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('1', 'true', 'yes', 'y')


class ExternalLeadWebhook(http.Controller):

    @http.route(
        '/webhook/crm-external-lead',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def receive_external_lead(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True)
        try:
            payload = json.loads(raw) if raw else dict(kwargs or {})
        except json.JSONDecodeError:
            payload = dict(kwargs or {})

        if not payload:
            return request.make_json_response(
                {'success': False, 'error': 'empty payload'}, status=400
            )

        # Normalise keys.
        lowered = {str(k).strip().lower(): v for k, v in payload.items()}

        category_raw = str(lowered.get('category', 'qualified')).strip().lower()
        category = _CATEGORY_ALIASES.get(category_raw)
        if not category:
            return request.make_json_response({
                'success': False,
                'error': "invalid category '%s' (use qualified | spam | technical)"
                         % category_raw,
            }, status=400)

        vals = {'category': category, 'raw_payload': json.dumps(payload, indent=2,
                                                                ensure_ascii=False)}
        for key, value in lowered.items():
            field = _FIELD_MAP.get(key)
            if field:
                vals[field] = value
        for bkey in _BOOL_FIELDS:
            if bkey in lowered:
                vals[bkey] = _to_bool(lowered[bkey])

        name = (vals.get('name') or '').strip()
        if not name:
            return request.make_json_response(
                {'success': False, 'error': "'name' is required"}, status=400
            )
        vals['name'] = name

        lead = request.env['crm.external.lead'].sudo().create(vals)
        _logger.info('External lead created | id=%s name=%s category=%s',
                     lead.id, lead.name, category)

        return request.make_json_response({
            'success': True,
            'id': lead.id,
            'name': lead.name,
            'category': category,
        })
