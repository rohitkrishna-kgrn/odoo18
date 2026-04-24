import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Fields that are "known" on crm.web.lead — everything else becomes form_data
_TARGET_FIELDS = {'name', 'contact_number', 'email', 'body', 'service'}


def _detect_source(data):
    """Return 'elementor' if payload looks like Elementor Pro, else 'any'."""
    fields_val = data.get('fields')
    if (
        isinstance(fields_val, list)
        and fields_val
        and isinstance(fields_val[0], dict)
        and 'value' in fields_val[0]
    ):
        return 'elementor'
    return 'any'


def _build_elementor_lookups(fields_list):
    """Return (by_id, by_title) lower-cased dicts from Elementor fields array."""
    by_id = {}
    by_title = {}
    for f in fields_list:
        if not isinstance(f, dict):
            continue
        fid = str(f.get('id', '')).strip().lower()
        ftitle = str(f.get('title', '')).strip().lower()
        value = f.get('value', '')
        if fid:
            by_id[fid] = {'value': value, 'raw': f}
        if ftitle:
            by_title[ftitle] = {'value': value, 'raw': f}
    return by_id, by_title


def _apply_mappings(env, data, source_type):
    """
    Apply configured field mappings and return:
      mapped_vals  – dict of crm.web.lead field values
      extra        – dict of unmapped data (goes to form_data)
    """
    mappings = env['crm.web.lead.field.map'].sudo().search([
        ('active', '=', True),
        ('source_type', 'in', [source_type, 'any']),
    ])

    mapped_vals = {}
    matched_source_keys = set()   # tracks what has been consumed

    if source_type == 'elementor':
        elementor_fields = data.get('fields', [])
        by_id, by_title = _build_elementor_lookups(elementor_fields)

        for m in mappings:
            key = (m.source_key or '').strip().lower()
            lookup = by_title if m.match_by == 'title' else by_id
            entry = lookup.get(key)
            if entry is not None and m.target_field not in mapped_vals:
                mapped_vals[m.target_field] = entry['value']
                matched_source_keys.add(key)

        # Collect unmapped elementor fields + meta into extra
        extra = {}
        for f in elementor_fields:
            fid = str(f.get('id', '')).strip().lower()
            ftitle = str(f.get('title', '')).strip().lower()
            if fid not in matched_source_keys and ftitle not in matched_source_keys:
                label = f.get('title') or f.get('id') or fid
                extra[label] = f.get('value', '')
        for meta_key in ('form_name', 'form_id', 'page_url', 'remote_ip', 'submitted_on'):
            if data.get(meta_key):
                extra[meta_key] = data[meta_key]

    else:
        # Flat JSON / custom source
        for m in mappings:
            key = (m.source_key or '').strip()
            if key in data and m.target_field not in mapped_vals:
                mapped_vals[m.target_field] = data[key]
                matched_source_keys.add(key)

        # Everything not consumed by a mapping and not a target field itself
        extra = {
            k: v for k, v in data.items()
            if k not in matched_source_keys
        }

    return mapped_vals, extra


class WebLeadWebhook(http.Controller):

    @http.route(
        '/webhook/web-lead',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def receive_web_lead(self, **kwargs):
        # ── Parse raw body ───────────────────────────────────────────────
        content_type = request.httprequest.content_type or ''
        raw = request.httprequest.get_data(as_text=True)

        if 'application/json' in content_type and raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
        else:
            # application/x-www-form-urlencoded (Elementor can send this too)
            data = {
                k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                for k, v in (kwargs or {}).items()
            }
            # Try parsing raw body as JSON anyway as a fallback
            if not data and raw:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    pass

        if not data:
            return request.make_json_response(
                {'success': False, 'error': 'empty payload'}, status=400
            )

        # ── Detect source & apply mappings ───────────────────────────────
        source_type = _detect_source(data)
        mapped_vals, extra = _apply_mappings(
            request.env, data, source_type
        )

        _logger.info(
            'Webhook received | source=%s | mapped=%s | extra_keys=%s',
            source_type, list(mapped_vals.keys()), list(extra.keys()),
        )

        # ── Validate required field ──────────────────────────────────────
        name = (mapped_vals.get('name') or '').strip()
        if not name:
            return request.make_json_response(
                {'success': False, 'error': 'name is required (no mapping resolved it)'},
                status=400,
            )

        vals = {
            'name': name,
            'contact_number': (mapped_vals.get('contact_number') or '').strip(),
            'email': (mapped_vals.get('email') or '').strip(),
            'body': (mapped_vals.get('body') or '').strip(),
            'service': (mapped_vals.get('service') or '').strip(),
            'form_data': json.dumps(extra, indent=2, ensure_ascii=False) if extra else '',
            'state': 'new',
        }

        lead = request.env['crm.web.lead'].sudo().create(vals)
        _logger.info(
            'Web lead created | id=%s name=%s source=%s',
            lead.id, lead.name, source_type,
        )

        return request.make_json_response({
            'success': True,
            'id': lead.id,
            'name': lead.name,
            'source': source_type,
        })
