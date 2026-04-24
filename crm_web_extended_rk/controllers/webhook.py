import json
import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


# ── Bracket-key parser ────────────────────────────────────────────────────────

def _parse_bracket_keys(flat):
    """
    Convert PHP-style bracket keys into a nested dict.
    {'fields[name][value]': 'John'} → {'fields': {'name': {'value': 'John'}}}
    """
    result = {}
    for key, val in flat.items():
        parts = [p for p in re.split(r'\[|\]\[|\]', key) if p]
        if len(parts) == 1:
            result[parts[0]] = val
        else:
            d = result
            for part in parts[:-1]:
                d = d.setdefault(part, {})
            d[parts[-1]] = val
    return result


# ── Source detection ──────────────────────────────────────────────────────────

def _detect_source(flat_data, parsed):
    """
    Return 'elementor' when the payload looks like Elementor Pro, else 'any'.

    Elementor Pro sends form-urlencoded with keys like:
        fields[name][value], fields[email][id], meta[page_url][value] …

    It may also occasionally send JSON with a 'fields' list of {id,title,value}.
    """
    # JSON format: fields is a list of {id, title, value}
    fields_json = flat_data.get('fields')
    if (
        isinstance(fields_json, list)
        and fields_json
        and isinstance(fields_json[0], dict)
        and 'value' in fields_json[0]
    ):
        return 'elementor_json'

    # Form-urlencoded bracket notation
    if isinstance(parsed.get('fields'), dict):
        return 'elementor'

    return 'any'


# ── Elementor field lookups ───────────────────────────────────────────────────

def _elementor_lookups_from_bracket(parsed_fields):
    """Build (by_id, by_title) dicts from bracket-parsed fields."""
    by_id, by_title = {}, {}
    for _bucket_key, fdata in parsed_fields.items():
        if not isinstance(fdata, dict):
            continue
        fid    = str(fdata.get('id',    _bucket_key)).strip().lower()
        ftitle = str(fdata.get('title', '')).strip().lower()
        value  = fdata.get('value', '')
        if fid:
            by_id[fid]     = {'value': value, 'raw': fdata}
        if ftitle:
            by_title[ftitle] = {'value': value, 'raw': fdata}
    return by_id, by_title


def _elementor_lookups_from_json(fields_list):
    """Build (by_id, by_title) dicts from Elementor JSON fields array."""
    by_id, by_title = {}, {}
    for f in fields_list:
        if not isinstance(f, dict):
            continue
        fid    = str(f.get('id',    '')).strip().lower()
        ftitle = str(f.get('title', '')).strip().lower()
        value  = f.get('value', '')
        if fid:
            by_id[fid]     = {'value': value, 'raw': f}
        if ftitle:
            by_title[ftitle] = {'value': value, 'raw': f}
    return by_id, by_title


# ── Mapping engine ────────────────────────────────────────────────────────────

def _apply_mappings(env, flat_data, parsed, source_type):
    """
    Apply saved field mappings.
    Returns (mapped_vals dict, extra dict for form_data).
    """
    mappings = env['crm.web.lead.field.map'].sudo().search([
        ('active', '=', True),
        ('source_type', 'in', [
            'elementor' if source_type in ('elementor', 'elementor_json') else source_type,
            'any',
        ]),
    ])

    mapped_vals     = {}
    matched_ids     = set()   # field id/key already consumed
    matched_titles  = set()

    # ── Elementor (bracket form-urlencoded) ──────────────────────────────
    if source_type == 'elementor':
        parsed_fields = parsed.get('fields', {})
        by_id, by_title = _elementor_lookups_from_bracket(parsed_fields)

        for m in mappings:
            if m.target_field in mapped_vals:
                continue
            key = (m.source_key or '').strip().lower()
            if m.match_by == 'title':
                entry = by_title.get(key)
                if entry:
                    mapped_vals[m.target_field] = entry['value']
                    matched_titles.add(key)
            else:
                entry = by_id.get(key)
                if entry:
                    mapped_vals[m.target_field] = entry['value']
                    matched_ids.add(key)

        # Unmapped elementor fields → extra
        extra = {}
        for _bk, fdata in parsed_fields.items():
            if not isinstance(fdata, dict):
                continue
            fid    = str(fdata.get('id',    _bk)).strip().lower()
            ftitle = str(fdata.get('title', '')).strip().lower()
            if fid not in matched_ids and ftitle not in matched_titles:
                label = fdata.get('title') or fdata.get('id') or _bk
                extra[label] = fdata.get('value', '')

        # Meta block (date, page_url, remote_ip, user_agent …)
        for _mk, mdata in parsed.get('meta', {}).items():
            if isinstance(mdata, dict):
                label = mdata.get('title') or _mk
                extra[label] = mdata.get('value', '')
        # Form info
        form_info = parsed.get('form', {})
        if isinstance(form_info, dict) and form_info.get('name'):
            extra['form_name'] = form_info['name']

    # ── Elementor JSON (fields list) ─────────────────────────────────────
    elif source_type == 'elementor_json':
        by_id, by_title = _elementor_lookups_from_json(flat_data.get('fields', []))

        for m in mappings:
            if m.target_field in mapped_vals:
                continue
            key = (m.source_key or '').strip().lower()
            lookup = by_title if m.match_by == 'title' else by_id
            entry  = lookup.get(key)
            if entry:
                mapped_vals[m.target_field] = entry['value']
                (matched_titles if m.match_by == 'title' else matched_ids).add(key)

        extra = {}
        for f in flat_data.get('fields', []):
            fid    = str(f.get('id',    '')).strip().lower()
            ftitle = str(f.get('title', '')).strip().lower()
            if fid not in matched_ids and ftitle not in matched_titles:
                extra[f.get('title') or f.get('id')] = f.get('value', '')
        for mk in ('form_name', 'form_id', 'page_url', 'remote_ip', 'submitted_on'):
            if flat_data.get(mk):
                extra[mk] = flat_data[mk]

    # ── Custom flat JSON / form-urlencoded ───────────────────────────────
    else:
        matched_keys = set()
        for m in mappings:
            if m.target_field in mapped_vals:
                continue
            key = (m.source_key or '').strip()
            if key in flat_data:
                mapped_vals[m.target_field] = flat_data[key]
                matched_keys.add(key)

        extra = {k: v for k, v in flat_data.items() if k not in matched_keys}

    return mapped_vals, extra


# ── Controller ────────────────────────────────────────────────────────────────

class WebLeadWebhook(http.Controller):

    @http.route(
        '/webhook/web-lead',
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
    )
    def receive_web_lead(self, **kwargs):
        content_type = request.httprequest.content_type or ''
        raw          = request.httprequest.get_data(as_text=True)

        # ── Parse payload ────────────────────────────────────────────────
        if 'application/json' in content_type and raw:
            try:
                flat_data = json.loads(raw)
            except json.JSONDecodeError:
                flat_data = {}
            parsed = {}
        else:
            # form-urlencoded (Elementor Pro default)
            flat_data = {
                k: (v[0] if isinstance(v, list) and len(v) == 1 else v)
                for k, v in (kwargs or {}).items()
            }
            if not flat_data and raw:
                # fallback: try raw as JSON
                try:
                    flat_data = json.loads(raw)
                except json.JSONDecodeError:
                    pass
            parsed = _parse_bracket_keys(flat_data)

        if not flat_data and not parsed:
            return request.make_json_response(
                {'success': False, 'error': 'empty payload'}, status=400
            )

        # ── Detect source & apply mappings ───────────────────────────────
        source_type          = _detect_source(flat_data, parsed)
        mapped_vals, extra   = _apply_mappings(
            request.env, flat_data, parsed, source_type
        )

        _logger.info(
            'Webhook | source=%s | mapped=%s | extra_keys=%s',
            source_type, list(mapped_vals.keys()), list(extra.keys()),
        )

        # ── Validate ─────────────────────────────────────────────────────
        name = (mapped_vals.get('name') or '').strip()
        if not name:
            _logger.warning(
                'Webhook rejected: name not resolved. mapped=%s flat_keys=%s',
                mapped_vals, list(flat_data.keys()),
            )
            return request.make_json_response(
                {'success': False, 'error': 'name could not be resolved from payload'},
                status=400,
            )

        vals = {
            'name':           name,
            'contact_number': (mapped_vals.get('contact_number') or '').strip(),
            'email':          (mapped_vals.get('email') or '').strip(),
            'body':           (mapped_vals.get('body') or '').strip(),
            'service':        (mapped_vals.get('service') or '').strip(),
            'form_data':      json.dumps(extra, indent=2, ensure_ascii=False) if extra else '',
            'state':          'new',
        }

        lead = request.env['crm.web.lead'].sudo().create(vals)
        _logger.info('Web lead created | id=%s name=%s source=%s', lead.id, lead.name, source_type)

        return request.make_json_response({
            'success': True,
            'id':      lead.id,
            'name':    lead.name,
            'source':  source_type,
        })
