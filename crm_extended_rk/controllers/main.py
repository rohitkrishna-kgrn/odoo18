# -*- coding: utf-8 -*-
import json

from odoo import _, http
from odoo.http import request

from ..models.discovery_schema import DISCOVERY_SECTIONS, entity_fields, iter_fields


class DiscoveryFormController(http.Controller):

    def _lead_for_token(self, token):
        """Resolve a lead by its discovery token (sudo — public visitor)."""
        if not token:
            return request.env['crm.lead']
        return request.env['crm.lead'].sudo().search(
            [('discovery_token', '=', token)], limit=1)

    def _logo_company(self, company):
        """Return a company that actually has a logo.

        For a public request `request.env.company` can resolve to a record whose
        `logo` is empty; fall back to the main company that has one (this is the
        same company whose logo the website login page renders).
        """
        company = company.sudo()
        if company and company.logo:
            return company
        return request.env['res.company'].sudo().search(
            [('logo', '!=', False)], order='id', limit=1) or company

    def _company_logo_src(self, company):
        """Inline the company logo as a base64 data URI (filestore-independent)."""
        logo = company.logo if company else False
        if not logo:
            return ''
        if isinstance(logo, bytes):
            logo = logo.decode('ascii')
        return 'data:image/png;base64,%s' % logo

    def _render(self, template, values):
        company = values.get('company') or request.env.company
        logo_company = self._logo_company(company)
        values.setdefault('company', company)
        values.setdefault('logo_company', logo_company)
        values.setdefault('logo_src', self._company_logo_src(logo_company))
        response = request.render(template, values)
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        return response

    def _form_values(self, lead, token, **extra):
        prefill = lead._discovery_prefill()
        values = {
            'company': request.env.company,
            'lead': lead,
            'token': token,
            'sections': DISCOVERY_SECTIONS,
            'prefill': prefill,
            'section_count': len(DISCOVERY_SECTIONS),
            'prefill_json': json.dumps(prefill, ensure_ascii=False),
            'submitted_payload': '{}',
            'errors': [],
        }
        values.update(extra)
        return values

    # ------------------------------------------------------------------
    # GET: render the form
    # ------------------------------------------------------------------
    @http.route(['/discovery-form/<string:token>'], type='http', auth='public',
                website=False, methods=['GET'], csrf=False, sitemap=False)
    def discovery_form(self, token, **kw):
        lead = self._lead_for_token(token)
        company = request.env.company

        if not lead:
            return self._render('crm_extended_rk.discovery_invalid', {'company': company})

        if lead.discovery_form_state == 'submitted':
            return self._render('crm_extended_rk.discovery_already_submitted', {
                'company': company,
                'lead': lead,
            })

        return self._render('crm_extended_rk.discovery_form',
                            self._form_values(lead, token))

    # ------------------------------------------------------------------
    # POST: accept the submission
    # ------------------------------------------------------------------
    @http.route(['/discovery-form/<string:token>/submit'], type='http', auth='public',
                website=False, methods=['POST'], csrf=True, sitemap=False)
    def discovery_submit(self, token, **post):
        lead = self._lead_for_token(token)
        company = request.env.company

        if not lead:
            return self._render('crm_extended_rk.discovery_invalid', {'company': company})
        if lead.discovery_form_state == 'submitted':
            return self._render('crm_extended_rk.discovery_already_submitted', {
                'company': company, 'lead': lead})

        # The whole answer set arrives as one JSON blob assembled by the front-end.
        try:
            payload = json.loads(post.get('payload') or '{}')
        except (ValueError, TypeError):
            payload = {}

        errors = self._validate(payload)
        if errors:
            return self._render('crm_extended_rk.discovery_form', self._form_values(
                lead, token, errors=errors, submitted_payload=post.get('payload') or '{}'))

        lead._apply_discovery_submission(payload)
        return self._render('crm_extended_rk.discovery_thanks', {
            'company': company, 'lead': lead})

    # ------------------------------------------------------------------
    # Server-side validation (front-end validates too; this is the backstop)
    # ------------------------------------------------------------------
    def _validate(self, payload):
        errors = []
        for _section, field in iter_fields(include_entities=False):
            if not field.get('required'):
                continue
            key = field['key']
            if field['type'] == 'signature':
                val = payload.get(key)
                if not (isinstance(val, str) and val.startswith('data:image')):
                    errors.append(field['label'])
                continue
            if field['type'] == 'checkbox_single':
                if not payload.get(key):
                    errors.append(field['label'])
                continue
            val = payload.get(key)
            if val in (None, '', [], {}):
                errors.append(field['label'])

        # Entity sub-form: at least one entity, each with its required fields.
        entities = payload.get('entities') or []
        if not entities:
            errors.append(_("At least one entity in scope"))
        for idx, ent in enumerate(entities, start=1):
            services = ent.get('services') or []
            for field in entity_fields():
                if not field.get('required'):
                    continue
                show_if = field.get('show_if')
                if show_if and not any(v in services for v in show_if['contains']):
                    continue
                val = ent.get(field['key'])
                if val in (None, '', [], {}):
                    errors.append(_("Entity %(n)s: %(label)s") % {
                        'n': idx, 'label': field['label']})
        return errors
