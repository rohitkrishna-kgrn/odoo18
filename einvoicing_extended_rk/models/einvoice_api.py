# -*- coding: utf-8 -*-
"""HTTP transport for the KGRN eInvoicing platform.

Kept in one place so every caller gets the same timeout handling, the same
redaction of the Authorization header in the logs, and the same
``(status, body, error)`` contract:

* ``error`` is not None only for a transport failure — nothing was decided
  about the request, and retrying with the same ``UniqueInvoiceNumber`` is safe.
* otherwise ``status`` is the HTTP status and ``body`` the decoded JSON.
"""
import json
import logging

import requests

from odoo import _, models

_logger = logging.getLogger(__name__)


class EinvoiceApi(models.AbstractModel):
    _name = 'einvoice.api'
    _description = 'KGRN eInvoicing HTTP Transport'

    def _request(self, method, url, token=None, payload=None, timeout=60, auth=None):
        headers = {'Accept': 'application/json'}
        if token:
            # Note the single space after Bearer.
            headers['Authorization'] = 'Bearer %s' % token
        if payload is not None:
            headers['Content-Type'] = 'application/json'

        try:
            response = requests.request(
                method, url, headers=headers, auth=auth, timeout=timeout,
                data=json.dumps(payload, default=str) if payload is not None else None,
            )
        except requests.exceptions.Timeout:
            msg = _('The eInvoicing platform did not answer within %ss. The '
                    'invoice may still have been received — retry with the '
                    'same Unique Invoice Number, it never creates a duplicate.',
                    timeout)
            _logger.warning('eInvoice: timeout calling %s', url)
            return 0, None, msg
        except requests.exceptions.RequestException as exc:
            _logger.warning('eInvoice: transport error calling %s: %s', url, exc)
            return 0, None, _('Could not reach the eInvoicing platform: %s', exc)

        try:
            body = response.json()
        except ValueError:
            body = {'error': (response.text or '')[:500]}

        _logger.info('eInvoice: %s %s -> HTTP %s', method, url, response.status_code)
        return response.status_code, body, None
