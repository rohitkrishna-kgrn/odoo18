# -*- coding: utf-8 -*-
import json

from odoo import _, http
from odoo.http import request

from ..models.discovery_schema import entity_fields, get_label, get_sections, iter_fields


class DiscoveryFormController(http.Controller):

    def _submission_for_token(self, token):
        """Resolve a discovery form submission by its access token (sudo — public visitor)."""
        if not token:
            return request.env['crm.lead.discovery.form']
        return request.env['crm.lead.discovery.form'].sudo().search(
            [('token', '=', token)], limit=1)

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

    def _form_values(self, submission, token, **extra):
        lead = submission.lead_id
        prefill = lead._discovery_prefill()
        sections = get_sections(submission.form_type)
        values = {
            'company': request.env.company,
            'lead': lead,
            'token': token,
            'sections': sections,
            'form_label': get_label(submission.form_type),
            'prefill': prefill,
            'section_count': len(sections),
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
        submission = self._submission_for_token(token)
        company = request.env.company

        if not submission:
            return self._render('crm_extended_rk.discovery_invalid', {'company': company})

        if submission.state == 'submitted':
            return self._render('crm_extended_rk.discovery_already_submitted', {
                'company': company,
                'lead': submission.lead_id,
            })

        return self._render('crm_extended_rk.discovery_form',
                            self._form_values(submission, token))

    # ------------------------------------------------------------------
    # POST: accept the submission
    # ------------------------------------------------------------------
    @http.route(['/discovery-form/<string:token>/submit'], type='http', auth='public',
                website=False, methods=['POST'], csrf=True, sitemap=False)
    def discovery_submit(self, token, **post):
        submission = self._submission_for_token(token)
        company = request.env.company

        if not submission:
            return self._render('crm_extended_rk.discovery_invalid', {'company': company})
        if submission.state == 'submitted':
            return self._render('crm_extended_rk.discovery_already_submitted', {
                'company': company, 'lead': submission.lead_id})

        # The whole answer set arrives as one JSON blob assembled by the front-end.
        try:
            payload = json.loads(post.get('payload') or '{}')
        except (ValueError, TypeError):
            payload = {}

        sections = get_sections(submission.form_type)
        errors = self._validate(sections, payload)
        if errors:
            return self._render('crm_extended_rk.discovery_form', self._form_values(
                submission, token, errors=errors, submitted_payload=post.get('payload') or '{}'))

        submission._apply_submission(payload)
        return self._render('crm_extended_rk.discovery_thanks', {
            'company': company, 'lead': submission.lead_id})

    # ------------------------------------------------------------------
    # Server-side validation (front-end validates too; this is the backstop)
    # ------------------------------------------------------------------
    @staticmethod
    def _field_visible(show_if, container):
        """Whether a conditionally-shown field is currently visible.

        `container` is the payload dict the sibling field lives in (the
        top-level payload, or a single entity dict for per-entity fields).
        """
        if not show_if:
            return True
        val = container.get(show_if['field'])
        if val is None:
            return False
        values = val if isinstance(val, list) else [val]
        return any(v in show_if['contains'] for v in values)

    def _validate(self, sections, payload):
        errors = []
        for _section, field in iter_fields(sections, include_entities=False):
            if not field.get('required'):
                continue
            if not self._field_visible(field.get('show_if'), payload):
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

        # Entity sub-form (only for schemas that define one): at least one
        # entity, each with its required (and currently visible) fields.
        ent_fields = entity_fields(sections)
        if ent_fields:
            entities = payload.get('entities') or []
            if not entities:
                errors.append(_("At least one entity in scope"))
            for idx, ent in enumerate(entities, start=1):
                for field in ent_fields:
                    if not field.get('required'):
                        continue
                    if not self._field_visible(field.get('show_if'), ent):
                        continue
                    val = ent.get(field['key'])
                    if val in (None, '', [], {}):
                        errors.append(_("Entity %(n)s: %(label)s") % {
                            'n': idx, 'label': field['label']})
        return errors
