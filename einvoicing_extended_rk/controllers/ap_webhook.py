# -*- coding: utf-8 -*-
"""AP inbound webhook — the endpoint the KGRN platform POSTs supplier documents to.

Contract, from the delivery specification:

* ``POST`` with ``Content-Type: application/json``; auth is whatever the entity's
  ``apErpWebhook.authType`` is set to — bearer, basic, apikey or none.
* Any ``2xx`` with any body is a valid ack; ``{"ok": true, "received": "<id>"}``
  is the recommended shape.
* ``4xx`` is treated as a **permanent** rejection and is never retried — so it
  is only returned for something a retry could not fix (bad auth, unusable
  body, unknown event).
* ``5xx`` and network failures get **one** immediate retry — so a transient
  problem on our side must answer 5xx, not 4xx, to earn that retry.
* Delivery is idempotency-keyed on ``document.instanceId``: a repeat is an
  upsert, never a duplicate.
* The push is aborted after 20 s, so the handler must stay quick.
"""
import base64
import binascii
import hmac
import json
import logging

from odoo import SUPERUSER_ID, _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.einvoicing_extended_rk.models.account_move_ap import EinvoiceRejected

_logger = logging.getLogger(__name__)


class EinvoiceApWebhook(http.Controller):

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def _authenticate(self, company):
        """Check the inbound credentials against the company configuration.

        Returns an error string, or None when the request is authorised.
        """
        headers = request.httprequest.headers
        auth_type = company.einv_ap_auth_type or 'bearer'

        if auth_type == 'none':
            return None

        if auth_type == 'bearer':
            expected = company.sudo().einv_ap_token
            if not expected:
                return 'Webhook token is not configured'
            header = headers.get('Authorization') or ''
            if not header.startswith('Bearer '):
                return 'Missing bearer token'
            return None if self._equal(header[7:].strip(), expected) else 'Invalid token'

        if auth_type == 'apikey':
            expected = company.sudo().einv_ap_token
            if not expected:
                return 'Webhook token is not configured'
            name = company.einv_ap_api_key_header or 'X-API-Key'
            return None if self._equal(headers.get(name) or '', expected) else 'Invalid API key'

        if auth_type == 'basic':
            header = headers.get('Authorization') or ''
            if not header.startswith('Basic '):
                return 'Missing basic credentials'
            try:
                decoded = base64.b64decode(header[6:].strip()).decode()
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return 'Malformed basic credentials'
            username, _sep, password = decoded.partition(':')
            ok = (self._equal(username, company.einv_ap_username or '')
                  and self._equal(password, company.sudo().einv_ap_password or ''))
            return None if ok else 'Invalid credentials'

        return 'Unsupported authentication type'

    @staticmethod
    def _equal(given, expected):
        """Constant-time comparison, so a wrong token cannot be guessed byte by byte."""
        return bool(expected) and hmac.compare_digest(str(given), str(expected))

    # ------------------------------------------------------------------
    # Endpoint
    # ------------------------------------------------------------------
    @http.route('/einvoicing/ap/webhook', type='http', auth='none',
                methods=['POST'], csrf=False, save_session=False)
    def ap_webhook(self, **kwargs):
        try:
            raw = request.httprequest.get_data(as_text=True)
            payload = json.loads(raw or '{}')
        except ValueError:
            # Malformed JSON will never parse on a retry.
            return self._reply(400, {'ok': False, 'error': 'Malformed JSON body'})
        if not isinstance(payload, dict):
            return self._reply(400, {'ok': False, 'error': 'Body must be a JSON object'})

        company = request.env['res.company'].sudo()._einv_find_by_ap_payload(payload)
        if not company:
            return self._reply(404, {
                'ok': False,
                'error': 'No company is configured for this entity — enable the '
                         'AP inbound webhook and set the KGRN Entity ID',
            })

        auth_error = self._authenticate(company)
        if auth_error:
            _logger.warning('eInvoice AP webhook: %s (company %s, ip %s)',
                            auth_error, company.name, request.httprequest.remote_addr)
            return self._reply(401, {'ok': False, 'error': auth_error})

        # The route is auth='none' so that the platform never needs an Odoo
        # login; the shared secret above is the authentication. Until this
        # point the environment carries no user at all, so anything touching
        # self.env.user raises — creating a vendor bill touches the chatter,
        # sequences and taxes, none of which work without one.
        request.update_env(user=SUPERUSER_ID, su=True)
        request.update_context(allowed_company_ids=[company.id])
        company = company.with_env(request.env)

        event = payload.get('event')

        # Connectivity probe: confirms URL + auth only. Nothing is persisted,
        # matching the platform's own "result not persisted" behaviour.
        if event == 'erp.webhook.test':
            _logger.info('eInvoice AP webhook: connectivity test for %s', company.name)
            return self._reply(200, {
                'ok': True,
                'received': (payload.get('document') or {}).get('id') or 'TEST',
                'company': company.name,
            })

        if event not in ('ap.invoice.received', 'ap.credit_note.received'):
            return self._reply(400, {
                'ok': False, 'error': 'Unsupported event "%s"' % (event or '')})

        document = payload.get('document') or {}
        try:
            move, action = request.env['account.move'].sudo()._einv_receive_document(
                payload, company)
        except (EinvoiceRejected, UserError, ValidationError) as exc:
            # A configuration or payload problem a retry cannot fix.
            request.env.cr.rollback()
            self._record_delivery(company, ok=False, error=str(exc))
            self._log(company, payload, success=False, message=str(exc), status=400)
            _logger.warning('eInvoice AP webhook: rejected — %s', exc)
            return self._reply(400, {'ok': False, 'error': str(exc)})
        except Exception as exc:
            # Transient on our side: answer 5xx so the platform retries once.
            request.env.cr.rollback()
            self._record_delivery(company, ok=False, error=str(exc))
            _logger.exception('eInvoice AP webhook: failed to store the document')
            return self._reply(500, {'ok': False, 'error': str(exc)})

        self._record_delivery(company, ok=True)
        self._log(company, payload, success=True, move=move, status=200,
                  message=_('Document %(action)s as %(name)s',
                            action=action, name=move.display_name))
        _logger.info('eInvoice AP webhook: %s %s -> %s (%s)',
                     event, document.get('id'), move.name, action)
        return self._reply(200, {
            'ok': True,
            'received': document.get('id') or move.name,
            'action': action,
            'odooId': move.id,
            'odooReference': move.name if move.name and move.name != '/' else move.ref,
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _reply(self, status, body):
        return request.make_json_response(body, status=status)

    def _record_delivery(self, company, ok=True, error=''):
        """Mirror the platform's own delivery-status fields on our side."""
        company.sudo().write({
            'einv_ap_last_status': 'ok' if ok else 'error',
            'einv_ap_last_date': fields.Datetime.now(),
            'einv_ap_last_error': (error or '')[:300],
        })

    def _log(self, company, payload, success, status, message='', move=None):
        document = payload.get('document') or {}
        request.env['einvoice.log'].sudo()._log({
            'company_id': company.id,
            'move_id': move.id if move else False,
            'direction': 'ap',
            'operation': 'test' if payload.get('event') == 'erp.webhook.test' else 'receive',
            'endpoint': '/einvoicing/ap/webhook',
            'http_status': status,
            'success': success,
            'instance_id': document.get('instanceId'),
            'record_id': document.get('recordId'),
            'unique_invoice_number': document.get('id'),
            'message': message,
            'request_body': payload,
        })
