# -*- coding: utf-8 -*-
import base64
import json

from odoo import api, models

from .discovery_schema import DISCOVERY_SECTIONS


class DiscoveryFormReport(models.AbstractModel):
    _name = 'report.crm_extended_rk.report_discovery_form_document'
    _description = 'Client Discovery Form PDF'

    # ------------------------------------------------------------------
    # Formatting helpers (schema-aware)
    # ------------------------------------------------------------------
    @staticmethod
    def _opt_label(field, value):
        for o in field.get('options') or []:
            if isinstance(o, dict) and o.get('value') == value:
                return o.get('label')
        return value

    @staticmethod
    def _code(label):
        """'Edition A — Standard...' -> 'Edition A' ; 'T1 — ...' -> 'T1'."""
        if not label:
            return ''
        return str(label).split('—')[0].strip()

    def _fmt_values(self, field, value):
        """Return a list of display strings for a single answer."""
        if value in (None, '', [], {}):
            return []
        ftype = field['type']
        if ftype == 'checkbox' and isinstance(value, list):
            return [self._opt_label(field, v) for v in value if v not in (None, '')]
        if ftype in ('select', 'radio'):
            return [self._opt_label(field, value)]
        if ftype == 'checkbox_single':
            return ['Confirmed'] if value else ['Not confirmed']
        return [str(value)]

    def _build_entities(self, answers):
        rows = []
        for ent in answers.get('entities') or []:
            opts = []
            if ent.get('s6Edition'):
                opts.append('S6: %s' % self._code(ent['s6Edition']))
            if ent.get('s7Tier'):
                opts.append('Support: %s' % self._code(ent['s7Tier']))
            if ent.get('s8Level'):
                opts.append('MS: %s' % self._code(ent['s8Level']))
            rows.append({
                'name': ent.get('entityName') or '',
                'erp': ent.get('erpSystem') or '',
                'outbound': ent.get('outboundCount') or '',
                'inbound': ent.get('inboundCount') or '',
                'services': ent.get('services') or [],
                'options': ' / '.join(opts),
            })
        return rows

    def _build_doc(self, lead):
        try:
            answers = json.loads(lead.discovery_data or '{}')
        except (ValueError, TypeError):
            answers = {}

        sections = []
        for section in DISCOVERY_SECTIONS:
            rows = []
            for field in section['fields']:
                if field['type'] == 'signature':
                    continue
                vals = self._fmt_values(field, answers.get(field['key']))
                if not vals:
                    continue
                rows.append({'label': field['label'], 'values': vals})

            entities = self._build_entities(answers) if section.get('entities') else []

            signature = ''
            if section['id'] == 'S09':
                sig = answers.get('signatureData')
                if isinstance(sig, str) and sig.startswith('data:image'):
                    signature = sig

            if rows or entities or signature:
                sections.append({
                    'id': section['id'],
                    'title': section['title'],
                    'rows': rows,
                    'entities': entities,
                    'signature': signature,
                })

        submitted = lead.discovery_submitted_date
        submitted_str = ''
        if submitted:
            submitted_str = submitted.strftime('%d %B %Y')
            if submitted_str.startswith('0'):
                submitted_str = submitted_str[1:]

        client = (answers.get('legalCompanyName') or lead.partner_name
                  or (lead.partner_id.name if lead.partner_id else '') or lead.name)
        contact = answers.get('primaryContactName') or lead.contact_name or client

        return {
            'order_ref': 'SE%05d' % lead.id,
            'client': client,
            'contact': contact,
            'submitted_str': submitted_str,
            'sections': sections,
        }

    def _logo_data_uri(self):
        """Return the company logo as a base64 data URI with the correct mime.

        Binary fields cannot be searched with `('logo', '!=', False)`, so we
        read candidates directly. Falls back to the company partner image.
        """
        company = self.env.company
        logo = company.logo
        if not logo:
            for comp in self.env['res.company'].sudo().search([], order='id'):
                if comp.logo:
                    logo = comp.logo
                    break
        if not logo and company.partner_id:
            logo = company.partner_id.image_1920
        if not logo:
            return ''

        logo_str = logo.decode('ascii') if isinstance(logo, bytes) else logo
        try:
            raw = base64.b64decode(logo_str)
        except Exception:
            return 'data:image/png;base64,%s' % logo_str

        mime = 'image/png'
        if raw[:3] == b'\xff\xd8\xff':
            mime = 'image/jpeg'
        elif raw[:6] in (b'GIF87a', b'GIF89a'):
            mime = 'image/gif'
        elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            mime = 'image/webp'
        elif b'<svg' in raw[:200].lower():
            mime = 'image/svg+xml'
        return 'data:%s;base64,%s' % (mime, logo_str)

    # ------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['crm.lead'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'crm.lead',
            'docs': docs,
            'company': self.env.company,
            'logo_src': self._logo_data_uri(),
            'report': {d.id: self._build_doc(d) for d in docs},
        }
