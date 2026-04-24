import json
import logging

from odoo import fields, http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class KgrnRecurringPortal(http.Controller):
    """Public-facing controller for the KGRN Recurring Payment customer portal.

    Routes are auth='public' so unauthenticated customers can access them.
    The ir_http override in models/ir_http.py bypasses the
    website_extended_rk login redirect for /kgrn/recurring/* paths.
    """

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_contract(self, token):
        """Return the contract for the given token or None."""
        if not token:
            return None
        return request.env['kgrn.recurring.contract'].sudo().search(
            [('access_token', '=', token)], limit=1
        )

    def _json_error(self, message, code=400):
        return Response(
            json.dumps({'error': message}),
            status=code,
            content_type='application/json',
        )

    def _json_ok(self, data=None):
        return Response(
            json.dumps(data or {'success': True}),
            status=200,
            content_type='application/json',
        )

    # -----------------------------------------------------------------------
    # Main portal page
    # -----------------------------------------------------------------------

    @http.route('/kgrn/recurring/card/<string:token>', type='http', auth='public', website=False)
    def portal_card_page(self, token, **kwargs):
        contract = self._get_contract(token)
        if not contract:
            return request.render('kgrn_recurring_payment.portal_error', {
                'error_title': 'Link Not Found',
                'error_message': (
                    'This payment link is invalid or has expired. '
                    'Please contact your account manager.'
                ),
            })

        # Determine page state
        state = contract.state
        card_added = bool(contract.stripe_payment_method_id)

        # Build payment schedule for display
        schedule = contract.get_payment_schedule(limit=24)

        payment_lines = contract.payment_line_ids.sorted('payment_date', reverse=True)

        values = {
            'contract': contract,
            'state': state,
            'card_added': card_added,
            'schedule': schedule,
            'payment_lines': payment_lines,
            'token': token,
            'publishable_key': contract._get_stripe_publishable_key(),
            'frequency_label': contract._get_frequency_label(),
        }
        return request.render('kgrn_recurring_payment.portal_card_page', values)

    # -----------------------------------------------------------------------
    # Create SetupIntent (AJAX – called by Stripe JS before card entry)
    # -----------------------------------------------------------------------

    @http.route(
        '/kgrn/recurring/card/<string:token>/create-setup-intent',
        type='http', auth='public', methods=['POST'], csrf=False, website=False,
    )
    def create_setup_intent(self, token, **kwargs):
        contract = self._get_contract(token)
        if not contract:
            return self._json_error('Invalid token.', 404)

        if contract.state in ('expired', 'cancelled'):
            return self._json_error('This contract is no longer active.')

        if contract.stripe_payment_method_id:
            return self._json_error('A payment card is already registered for this contract.')

        try:
            customer_id = contract._ensure_stripe_customer()
            api = contract._get_stripe_api()
            result = api.create_setup_intent(customer_id, contract.name)

            if result.get('error'):
                return self._json_error(result['error']['message'])

            return self._json_ok({
                'client_secret': result['client_secret'],
                'setup_intent_id': result['id'],
            })
        except Exception as e:
            _logger.exception('Error creating SetupIntent for token %s', token)
            return self._json_error(str(e))

    # -----------------------------------------------------------------------
    # Confirm card save (AJAX – called after Stripe.js confirmCardSetup)
    # -----------------------------------------------------------------------

    @http.route(
        '/kgrn/recurring/card/<string:token>/save-card',
        type='http', auth='public', methods=['POST'], csrf=False, website=False,
    )
    def save_card(self, token, **kwargs):
        contract = self._get_contract(token)
        if not contract:
            return self._json_error('Invalid token.', 404)

        if contract.state in ('expired', 'cancelled'):
            return self._json_error('This contract is no longer active.')

        raw = request.httprequest.get_data()
        try:
            body = json.loads(raw)
        except Exception:
            return self._json_error('Invalid request body.')

        payment_method_id = body.get('payment_method_id', '').strip()
        card_holder_name = body.get('card_holder_name', '').strip()

        if not payment_method_id:
            return self._json_error('No payment method ID received.')

        try:
            api = contract._get_stripe_api()

            # Retrieve payment method details
            pm = api.get_payment_method(payment_method_id)
            if pm.get('error'):
                return self._json_error(pm['error']['message'])

            card_data = pm.get('card', {})

            # Attach to Stripe customer if not already
            if pm.get('customer') != contract.stripe_customer_id:
                attach_result = api.attach_payment_method(
                    payment_method_id, contract.stripe_customer_id
                )
                if attach_result.get('error'):
                    return self._json_error(attach_result['error']['message'])

            # Persist card details on contract
            contract.write({
                'stripe_payment_method_id': payment_method_id,
                'card_brand': (card_data.get('brand') or '').upper(),
                'card_last4': card_data.get('last4', ''),
                'card_exp_month': card_data.get('exp_month', 0),
                'card_exp_year': card_data.get('exp_year', 0),
                'card_added_date': fields.Datetime.now(),
                'card_holder_name': card_holder_name or contract.customer_id.name,
            })

            # Auto-activate if start_date has already arrived
            today = fields.Date.today()
            if contract.state == 'draft' and contract.start_date and contract.start_date <= today:
                contract._do_activate()

            # Notify responsible user
            contract.message_post(
                body=(
                    f'Customer <strong>{contract.customer_id.name}</strong> has successfully '
                    f'registered their payment card '
                    f'({card_data.get("brand", "").upper()} •••• {card_data.get("last4", "")}).'
                ),
                partner_ids=[contract.user_id.partner_id.id] if contract.user_id else [],
                subtype_xmlid='mail.mt_comment',
            )

            return self._json_ok({
                'card_brand': (card_data.get('brand') or '').upper(),
                'card_last4': card_data.get('last4', ''),
                'contract_state': contract.state,
            })

        except Exception as e:
            _logger.exception('Error saving card for token %s', token)
            return self._json_error(str(e))

    # -----------------------------------------------------------------------
    # Customer requests card removal / service cancellation
    # -----------------------------------------------------------------------

    @http.route(
        '/kgrn/recurring/card/<string:token>/request-removal',
        type='http', auth='public', methods=['POST'], csrf=False, website=False,
    )
    def request_card_removal(self, token, **kwargs):
        contract = self._get_contract(token)
        if not contract:
            return self._json_error('Invalid token.', 404)

        if not contract.stripe_payment_method_id:
            return self._json_error('No card is registered on this contract.')

        if contract.card_removal_requested:
            return self._json_error('A removal request is already pending.')

        raw = request.httprequest.get_data()
        try:
            body = json.loads(raw)
        except Exception:
            body = {}

        reason = (body.get('reason') or '').strip()

        contract.write({
            'card_removal_requested': True,
            'card_removal_reason': reason or 'No reason provided.',
            'card_removal_request_date': fields.Datetime.now(),
        })
        contract._notify_card_removal_request()

        return self._json_ok({'message': 'Your request has been submitted. We will contact you shortly.'})

    # -----------------------------------------------------------------------
    # Stripe webhook handler
    # -----------------------------------------------------------------------

    @http.route(
        '/kgrn/recurring/webhook/stripe',
        type='http', auth='public', methods=['POST'], csrf=False, website=False,
    )
    def stripe_webhook(self, **kwargs):
        raw_body = request.httprequest.get_data()
        sig_header = request.httprequest.headers.get('Stripe-Signature', '')

        # We accept from any Stripe provider that has a webhook secret
        providers = request.env['payment.provider'].sudo().search([('code', '=', 'stripe')])
        verified = False
        for provider in providers:
            secret = getattr(provider, 'stripe_webhook_secret', False)
            if secret:
                from odoo.addons.kgrn_recurring_payment.models.kgrn_recurring_contract import _StripeAPI
                if _StripeAPI.verify_webhook(raw_body, sig_header, secret):
                    verified = True
                    break

        if not verified:
            _logger.warning('Unverified Stripe webhook received.')
            return Response('Unauthorized', status=401)

        try:
            event = json.loads(raw_body)
        except Exception:
            return Response('Bad Request', status=400)

        event_type = event.get('type', '')
        _logger.info('Stripe webhook received: %s', event_type)

        if event_type == 'payment_intent.succeeded':
            self._handle_payment_intent_succeeded(event['data']['object'])
        elif event_type == 'payment_intent.payment_failed':
            self._handle_payment_intent_failed(event['data']['object'])

        return Response('OK', status=200)

    def _handle_payment_intent_succeeded(self, intent):
        pi_id = intent.get('id')
        line = request.env['kgrn.recurring.payment.line'].sudo().search(
            [('stripe_payment_intent_id', '=', pi_id)], limit=1
        )
        if line and line.state == 'pending':
            line.write({'state': 'success'})

    def _handle_payment_intent_failed(self, intent):
        pi_id = intent.get('id')
        line = request.env['kgrn.recurring.payment.line'].sudo().search(
            [('stripe_payment_intent_id', '=', pi_id)], limit=1
        )
        if line and line.state == 'pending':
            reason = (
                intent.get('last_payment_error', {}) or {}
            ).get('message', 'Unknown error')
            line.write({'state': 'failed', 'failure_reason': reason})
