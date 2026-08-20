# -*- coding: utf-8 -*-
"""Issue an outbound API token without going through the portal UI.

``POST {API_BASE}/access-token/generate`` takes the portal credentials of an
entity administrator and returns a ``kgrn_out_`` token — no one-time code, so it
is usable from here.

The token is returned **once** and only its SHA-256 hash is stored on the
platform, so it is written straight onto the company. The password is never
stored: the guide is explicit that ERP configuration must not carry portal
credentials to re-issue tokens automatically.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EinvoiceTokenWizard(models.TransientModel):
    _name = 'einvoice.token.wizard'
    _description = 'Generate an Outbound eInvoicing API Token'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    api_base_url = fields.Char(
        string='API Base URL', related='company_id.einv_api_base_url', readonly=False)
    email = fields.Char(
        string='Portal Email', required=True,
        compute='_compute_email', store=True, readonly=False,
        help='The EmaraTax email registered for the entity, or the portal '
             'login email. The caller must be an entity administrator.')
    password = fields.Char(
        string='Portal Password', required=True,
        help='Used for this call only and never stored.')
    expires_at = fields.Datetime(
        string='Expires At', required=True,
        default=lambda self: fields.Datetime.now() + relativedelta(years=1),
        help='Must be in the future. Diarise the renewal — rotate by issuing '
             'the new token, switching Odoo over, then revoking the old one.')
    name = fields.Char(
        string='Token Name', default='Odoo production integration',
        help='Shown in the portal token list.')
    erp_name = fields.Char(string='ERP Name', default='Odoo')
    entity_id = fields.Char(
        string='Entity ID', related='company_id.einv_entity_id', readonly=False,
        help='Only needed when the login covers more than one entity.')
    location_id = fields.Char(
        string='Location ID', related='company_id.einv_location_id', readonly=False,
        help='Leave empty to use the entity primary location.')
    reason = fields.Char(
        string='Reason', default='AR push from Odoo',
        help='Free text, stored in the platform audit trail.')

    @api.depends('company_id')
    def _compute_email(self):
        for wizard in self:
            wizard.email = wizard.company_id.einv_portal_email or wizard.company_id.email

    def action_generate(self):
        self.ensure_one()
        company = self.company_id
        if self.expires_at <= fields.Datetime.now():
            raise UserError(_('The expiry must be in the future.'))

        payload = {
            'email': self.email,
            'password': self.password,
            'expiresAt': self.expires_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        }
        for value, key in ((self.name, 'name'), (self.erp_name, 'erpName'),
                           (self.location_id, 'locationId'),
                           (self.entity_id, 'entityId'), (self.reason, 'reason')):
            if value:
                payload[key] = value

        url = company._einv_api_url('access-token/generate')
        status, body, error = self.env['einvoice.api']._request(
            'POST', url, payload=payload, timeout=company.einv_timeout or 60)

        # The password must never reach the log.
        logged_request = dict(payload, password='***')
        logged_response = dict(body or {})
        if logged_response.get('token'):
            logged_response['token'] = '***'

        if error is not None or status != 201 or not (body or {}).get('token'):
            message = error or (body or {}).get('error') \
                or _('HTTP %s from the platform.', status)
            self.env['einvoice.log']._log({
                'company_id': company.id, 'direction': 'ar', 'operation': 'token',
                'endpoint': url, 'http_status': status, 'success': False,
                'message': message, 'request_body': logged_request,
                'response_body': logged_response,
            })
            raise UserError(_('Could not issue a token:\n\n%s') % message)

        entity = body.get('entity') or {}
        location = body.get('location') or {}
        company.sudo().write({
            'einv_api_token': body['token'],
            'einv_token_prefix': body.get('tokenPrefix'),
            'einv_token_name': body.get('name') or self.name,
            'einv_erp_name': body.get('erpName') or self.erp_name,
            'einv_token_expiry': self.expires_at,
            'einv_entity_id': entity.get('id') or company.einv_entity_id,
            'einv_entity_name': entity.get('name'),
            'einv_entity_trn': entity.get('trn'),
            'einv_location_id': location.get('id') or company.einv_location_id,
            'einv_location_name': location.get('name'),
            'einv_portal_email': self.email,
            'einv_connection_state': 'ok',
            'einv_connection_message': _(
                'Token issued for %(entity)s, location %(loc)s%(defaulted)s.',
                entity=entity.get('name') or '?',
                loc=location.get('name') or '?',
                defaulted=_(' (primary, defaulted)') if location.get('defaulted') else ''),
        })
        self.env['einvoice.log']._log({
            'company_id': company.id, 'direction': 'ar', 'operation': 'token',
            'endpoint': url, 'http_status': status, 'success': True,
            'record_id': body.get('id'),
            'message': _('Token %s issued.', body.get('tokenPrefix') or ''),
            'request_body': logged_request, 'response_body': logged_response,
        })
        return {'type': 'ir.actions.act_window_close'}
