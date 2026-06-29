import logging

from markupsafe import Markup
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


def _safe_get(record, fname):
    """Read a field value from a record; return empty string on any error."""
    try:
        val = getattr(record, fname, False)
        return val if val else ''
    except Exception:
        return ''


class CustomerFormController(http.Controller):

    # ── Public open form (no token required) ──────────────────────────────
    @http.route('/customer-form', type='http', auth='public', methods=['GET'], csrf=False)
    def customer_form_open(self, **kwargs):
        env = request.env
        country_list = []
        for c in env['res.country'].sudo().search([], order='name'):
            country_list.append({'id': str(c.id), 'name': c.name or '', 'selected': False})

        p = {f: '' for f in [
            'name', 'company_name', 'function',
            'email', 'phone', 'mobile', 'website',
            'street', 'street2', 'city', 'zip', 'vat',
            'emirates_id', 'passport_number', 'company_license_no',
            'country_id', 'country_name', 'state_id', 'state_name',
        ]}

        try:
            return request.render('contact_extended_rk.template_customer_form', {
                'form_action': '/customer-form/submit',
                'expiry_str': 'N/A',
                'is_company': False,
                'has_partner': False,
                'p': p,
                'country_list': country_list,
                'state_list': [],
            })
        except Exception:
            _logger.exception('Error rendering open customer form')
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'An error occurred loading the form. Please try again.'})

    @http.route('/customer-form/submit', type='http', auth='public', methods=['POST'], csrf=False)
    def customer_form_open_submit(self, **kwargs):
        env = request.env
        char_fields = [
            'name', 'email', 'phone', 'mobile', 'website',
            'company_name', 'function',
            'street', 'street2', 'city', 'zip',
            'vat', 'emirates_id', 'passport_number', 'company_license_no',
        ]
        vals = {}
        for fname in char_fields:
            value = (kwargs.get(fname) or '').strip()
            if value:
                vals[fname] = value

        country_raw = (kwargs.get('country_id') or '').strip()
        if country_raw:
            try:
                vals['country_id'] = int(country_raw)
            except ValueError:
                pass

        state_raw = (kwargs.get('state_id') or '').strip()
        if state_raw:
            try:
                vals['state_id'] = int(state_raw)
            except ValueError:
                pass

        if not vals.get('name'):
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'Full Name is required.'})

        save_ctx = {'no_vat_validation': True, 'tracking_disable': True}
        try:
            partner = env['res.partner'].sudo().with_context(**save_ctx).create(vals)
        except Exception as e:
            _logger.exception('Error creating partner from open customer form: %s', e)
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'There was an error saving your information: %s' % str(e)})

        try:
            now_str = fields.Datetime.now().strftime('%d %b %Y %H:%M')
            partner.sudo().message_post(
                body=Markup(
                    '<p>Customer Information Form submitted via public form on %s UTC.</p>'
                ) % now_str,
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.exception('Chatter log failed for open customer form (partner=%s)', partner.id)

        return request.render('contact_extended_rk.template_form_success', {
            'partner_name': _safe_get(partner, 'name') or '',
        })

    # ── Token-based form (sent via email) ─────────────────────────────────
    @http.route('/customer-form/<string:token>', type='http', auth='public', methods=['GET'], csrf=False)
    def customer_form(self, token, **kwargs):
        env = request.env
        token_rec = env['contact.form.token'].sudo().search(
            [('token', '=', token)], limit=1
        )

        if not token_rec:
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'This form link is invalid.'})

        if token_rec.state == 'submitted':
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'This form has already been submitted. Thank you!'})

        if token_rec.expiry_date and token_rec.expiry_date < fields.Datetime.now():
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'This form link has expired. Please contact us to request a new link.'})

        # Extract partner data as plain Python values — no ORM calls inside QWeb
        partner = token_rec.partner_id.sudo()
        char_fields = [
            'name', 'company_name', 'function',
            'email', 'phone', 'mobile', 'website',
            'street', 'street2', 'city', 'zip', 'vat',
            'emirates_id', 'passport_number', 'company_license_no',
        ]
        p = {f: '' for f in char_fields}
        p['country_id'] = ''
        p['country_name'] = ''
        p['state_id'] = ''
        p['state_name'] = ''
        is_company = False
        has_partner = False

        if partner:
            has_partner = True
            try:
                is_company = bool(partner.is_company)
            except Exception:
                is_company = False
            for f in char_fields:
                p[f] = _safe_get(partner, f)
            try:
                cid = partner.sudo().country_id
                if cid:
                    p['country_id'] = str(cid.id)
                    p['country_name'] = cid.name or ''
            except Exception:
                pass
            try:
                sid = partner.sudo().state_id
                if sid:
                    p['state_id'] = str(sid.id)
                    p['state_name'] = sid.name or ''
            except Exception:
                pass

        expiry_str = (token_rec.expiry_date.strftime('%d %b %Y')
                      if token_rec.expiry_date else 'N/A')

        country_list = []
        for c in env['res.country'].sudo().search([], order='name'):
            country_list.append({
                'id': str(c.id),
                'name': c.name or '',
                'selected': str(c.id) == p['country_id'],
            })

        # States filtered to the partner's current country (if set)
        state_domain = [('country_id', '=', int(p['country_id']))] if p['country_id'] else []
        state_list = []
        for s in env['res.country.state'].sudo().search(state_domain, order='name'):
            state_list.append({
                'id': str(s.id),
                'name': s.name or '',
                'selected': str(s.id) == p['state_id'],
            })

        try:
            return request.render('contact_extended_rk.template_customer_form', {
                'form_action': '/customer-form/%s/submit' % token_rec.token,
                'expiry_str': expiry_str,
                'is_company': is_company,
                'has_partner': has_partner,
                'p': p,
                'country_list': country_list,
                'state_list': state_list,
            })
        except Exception:
            _logger.exception('Error rendering customer form for token %s', token)
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'An error occurred loading the form. Please try again or contact support.'})

    @http.route('/customer-form/<string:token>/submit', type='http', auth='public', methods=['POST'], csrf=False)
    def customer_form_submit(self, token, **kwargs):
        env = request.env
        token_rec = env['contact.form.token'].sudo().search(
            [('token', '=', token), ('state', '=', 'pending')], limit=1
        )

        if not token_rec:
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'This form link is invalid or has already been submitted.'})

        if token_rec.expiry_date and token_rec.expiry_date < fields.Datetime.now():
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'This form link has expired. Please contact us to request a new link.'})

        # Collect submitted form values
        char_fields = [
            'name', 'email', 'phone', 'mobile', 'website',
            'company_name', 'function',
            'street', 'street2', 'city', 'zip',
            'vat', 'emirates_id', 'passport_number', 'company_license_no',
        ]
        vals = {}
        for fname in char_fields:
            value = (kwargs.get(fname) or '').strip()
            if value:
                vals[fname] = value

        country_raw = (kwargs.get('country_id') or '').strip()
        if country_raw:
            try:
                vals['country_id'] = int(country_raw)
            except ValueError:
                pass

        state_raw = (kwargs.get('state_id') or '').strip()
        if state_raw:
            try:
                vals['state_id'] = int(state_raw)
            except ValueError:
                pass

        # Save to partner record.
        # no_vat_validation=True bypasses Odoo's @api.constrains VAT format check
        # which fires whenever vat or country_id is written, even under sudo().
        save_ctx = {'no_vat_validation': True, 'tracking_disable': True}
        try:
            partner = token_rec.partner_id
            if partner:
                partner.sudo().with_context(**save_ctx).write(vals)
            else:
                partner = env['res.partner'].sudo().with_context(**save_ctx).create(vals)
                token_rec.sudo().write({'partner_id': partner.id})
        except Exception as e:
            _logger.exception('Error saving partner data from customer form (token=%s): %s', token, e)
            return request.render('contact_extended_rk.template_form_invalid',
                                  {'message': 'There was an error saving your information: %s' % str(e)})

        # Mark token as submitted
        token_rec.sudo().write({
            'state': 'submitted',
            'submitted_date': fields.Datetime.now(),
        })

        # Log in chatter (non-critical — failure must not block the success page)
        try:
            now_str = fields.Datetime.now().strftime('%d %b %Y %H:%M')
            partner_name = _safe_get(partner, 'name') or 'Unknown'
            contact_type = 'Entity' if partner.is_company else 'Individual'
            partner.sudo().message_post(
                body=Markup(
                    '<p>Customer Information Form submitted by <strong>%s</strong> (%s) on %s UTC.</p>'
                ) % (partner_name, contact_type, now_str),
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.exception('Chatter log failed for customer form (token=%s)', token)

        partner_name = _safe_get(partner, 'name') or ''
        return request.render('contact_extended_rk.template_form_success', {
            'partner_name': partner_name,
        })
