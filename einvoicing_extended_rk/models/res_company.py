# -*- coding: utf-8 -*-
import logging
import secrets

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import einvoice_lookups as lk

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    """KGRN eInvoicing configuration.

    Everything lives on the company rather than on ``ir.config_parameter``
    because a token is bound to exactly one KGRN entity + location, and this
    database runs several companies — each of which is its own FTA entity with
    its own token, its own quota and its own inbound webhook.
    """
    _inherit = 'res.company'

    # ------------------------------------------------------------------
    # AR — outbound (Odoo -> KGRN)
    # ------------------------------------------------------------------
    einv_enabled = fields.Boolean(
        string='Enable KGRN eInvoicing',
        help='Master switch for pushing AR invoices to the KGRN eInvoicing platform.',
    )
    einv_api_base_url = fields.Char(
        string='API Base URL',
        default='https://uat.kgrnaudit.com/api/v1',
        help='Environment host plus API base path, e.g. '
             'https://uat.kgrnaudit.com/api/v1 (UAT) — no trailing slash. '
             'UAT and production differ; never point a UAT token at production.',
    )
    einv_api_token = fields.Char(
        string='Outbound API Token',
        groups='base.group_system',
        help='The per-entity outbound token (kgrn_out_ prefix) issued in the '
             'client portal under Settings > Access tokens, or by the Generate '
             'Token wizard. Shown once at creation and stored hashed on the '
             'platform side — if it is lost, revoke it and issue a new one.',
    )
    einv_token_expiry = fields.Datetime(
        string='Token Expires On',
        help='Recorded when the token is issued through the wizard. The '
             'expiry-warning cron alerts before this date.',
    )
    einv_token_name = fields.Char(string='Token Name')
    einv_token_prefix = fields.Char(
        string='Token Prefix', readonly=True,
        help='The masked form of the token, as shown in the portal token list.',
    )
    einv_erp_name = fields.Char(
        string='ERP Name', default='Odoo',
        help='Which ERP consumes the token — shown in the portal token list.',
    )

    # Identifiers resolved from the token (filled by Test Connection / whoami).
    einv_entity_id = fields.Char(
        string='KGRN Entity ID',
        help='The platform entity id. Copy it from Settings > Active tokens > '
             '"API identifiers" in the portal. Only needed when the portal '
             'login covers more than one entity, and to route inbound AP '
             'documents to this company.',
    )
    einv_location_id = fields.Char(
        string='KGRN Location ID',
        help='Optional. Leave empty and the entity primary location is used.',
    )
    einv_entity_name = fields.Char(string='Entity Name', readonly=True)
    einv_entity_trn = fields.Char(string='Entity TRN', readonly=True)
    einv_location_name = fields.Char(string='Location Name', readonly=True)
    einv_peppol_sender_id = fields.Char(
        string='Peppol Sender ID', readonly=True,
        help='The entity Peppol participant id, e.g. 0235:100057476200003.',
    )
    einv_connection_state = fields.Selection(
        [('unknown', 'Not tested'), ('ok', 'Connected'), ('error', 'Failed')],
        string='Connection', default='unknown', readonly=True,
    )
    einv_connection_message = fields.Text(string='Connection Result', readonly=True)

    # Push behaviour.
    einv_default_push_state = fields.Selection(
        [('draft', 'Draft — store only'), ('submit', 'Submit — clear with the FTA')],
        string='Default Push Mode', default='draft',
        help='"draft" validates and stores the invoice on the platform without '
             'contacting the Access Point — use it while proving the field '
             'mapping. "submit" also transmits a valid invoice for clearance.',
    )
    einv_auto_push = fields.Boolean(
        string='Push on Post',
        help='Push a customer invoice / credit note to the platform '
             'automatically when it is posted. Failures never block posting; '
             'they are recorded on the invoice and can be retried.',
    )
    einv_attach_pdf = fields.Boolean(
        string='Attach Invoice PDF',
        help='Render the invoice report and send it in attachments[] as base64.',
    )
    einv_timeout = fields.Integer(
        string='Request Timeout (s)', default=60,
        help='A submit call waits for the Access Point response — 60s is the '
             'documented recommendation.',
    )

    # Seller / organisation defaults. The platform always overrides the seller
    # block from the entity profile, but the fields are still sent so the
    # payload mirrors what the portal AR detail view shows.
    einv_seller_scheme_id = fields.Char(
        string='Seller Scheme ID', default='0235',
        help='Peppol scheme identifier for the seller electronic address. '
             '0235 is the UAE TRN scheme.',
    )
    einv_seller_electronic_address = fields.Char(
        string='Seller Electronic Address',
        help='The seller Peppol participant id. Defaults to the company TRN.',
    )
    einv_legal_reg_type = fields.Selection(
        lk.LEGAL_REG_TYPE_CODES, string='Legal Registration Type', default='TL',
    )
    einv_legal_reg_id = fields.Char(string='Legal Registration Identifier')
    einv_trade_license = fields.Char(string='Commercial / Trade Licence')
    einv_authority_name = fields.Char(
        string='Issuing Authority', default='Department of Economic Development',
    )
    einv_contact_point = fields.Char(string='Seller Contact Point', default='Finance Department')
    einv_default_transaction_type = fields.Selection(
        lk.TRANSACTION_TYPE_CODES, string='Default Transaction Type', default='00000000',
        help='Rule BTUAE-002 makes this mandatory for AE sellers.',
    )
    einv_default_payment_means = fields.Selection(
        lk.PAYMENT_MEANS_CODES, string='Default Payment Means', default='30',
        help='Rule AE-PMC makes this mandatory on 380 / 389 documents.',
    )
    einv_default_item_type = fields.Selection(
        lk.ITEM_TYPE_CODES, string='Default Item Type', default='S',
        help='Used for lines whose product carries no item type. Services need '
             'a SAC code, goods need an HS classification.',
    )

    # Portal credentials, only used by the token-generation wizard. They are
    # deliberately NOT used to mint a token per push — the guide is explicit
    # that ERP configuration must not carry portal credentials for that.
    einv_portal_email = fields.Char(
        string='Portal Email', groups='base.group_system',
        help='EmaraTax email or portal login email of an entity administrator. '
             'Used only by the Generate Token wizard.',
    )

    # ------------------------------------------------------------------
    # AP — inbound (KGRN -> Odoo)
    # ------------------------------------------------------------------
    einv_ap_enabled = fields.Boolean(
        string='Enable AP Inbound Webhook',
        help='Accept supplier documents pushed by the platform at '
             '/einvoicing/ap/webhook and turn them into vendor bills and '
             'vendor credit notes.',
    )
    einv_ap_auth_type = fields.Selection(
        [('bearer', 'Bearer token'),
         ('apikey', 'API key header'),
         ('basic', 'Basic authentication'),
         ('none', 'No authentication')],
        string='Webhook Authentication', default='bearer',
        help='Must match apErpWebhook.authType configured on the KGRN side. '
             '"No authentication" leaves the endpoint open to anyone who '
             'guesses the URL and is only appropriate behind a private network.',
    )
    einv_ap_token = fields.Char(
        string='Webhook Token', groups='base.group_system',
        help='The shared secret this Odoo expects. For "Bearer token" the '
             'platform sends it as Authorization: Bearer <token>; for "API key '
             'header" it is the value of the configured header.',
    )
    einv_ap_api_key_header = fields.Char(
        string='API Key Header', default='X-API-Key',
        help='Header name for the "API key header" authentication type.',
    )
    einv_ap_username = fields.Char(string='Basic Auth Username')
    einv_ap_password = fields.Char(string='Basic Auth Password', groups='base.group_system')
    einv_ap_webhook_url = fields.Char(
        string='Webhook URL', compute='_compute_einv_ap_webhook_url',
        help='Configure this URL on the KGRN side under Connectors / ERP webhook.',
    )
    einv_ap_journal_id = fields.Many2one(
        'account.journal', string='AP Journal',
        domain="[('type', '=', 'purchase'), ('company_id', '=', id)]",
        help='Journal the inbound vendor bills and credit notes are booked in. '
             'Falls back to the first purchase journal of the company.',
    )
    einv_ap_auto_post = fields.Boolean(
        string='Auto-post Inbound Documents',
        help='Post the vendor bill as soon as it is received. Leave off to '
             'review each document first — recommended, because a received '
             'Peppol document is never blocked by the platform and its lines '
             'still need accounts and taxes checked.',
    )
    einv_ap_create_partner = fields.Boolean(
        string='Create Unknown Vendors', default=True,
        help='Create a vendor record when the supplier TRN / Peppol id / name '
             'matches nothing in the address book.',
    )
    einv_ap_product_id = fields.Many2one(
        'product.product', string='Fallback Product',
        help='Optional. Used on inbound lines when no product matches.',
    )
    einv_ap_account_id = fields.Many2one(
        'account.account', string='Fallback Expense Account',
        domain="[('company_ids', 'in', id), ('deprecated', '=', False)]",
        help='Expense account for inbound lines when neither the product nor '
             'the vendor supplies one.',
    )
    einv_ap_tax_id = fields.Many2one(
        'account.tax', string='Fallback Purchase Tax',
        domain="[('type_tax_use', '=', 'purchase'), ('company_id', '=', id)]",
        help='Used when the inbound VAT category and rate match no purchase tax.',
    )
    einv_ap_store_xml = fields.Boolean(
        string='Store Received UBL', default=True,
        help='Attach document.xml to the created bill when the platform is '
             'configured with includeXml.',
    )
    einv_ap_last_status = fields.Selection(
        [('ok', 'OK'), ('error', 'Error')], string='Last Delivery', readonly=True,
    )
    einv_ap_last_date = fields.Datetime(string='Last Delivery At', readonly=True)
    einv_ap_last_error = fields.Char(string='Last Delivery Error', readonly=True)

    # ------------------------------------------------------------------
    # Computes / helpers
    # ------------------------------------------------------------------
    def _compute_einv_ap_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for company in self:
            company.einv_ap_webhook_url = '%s/einvoicing/ap/webhook' % base.rstrip('/')

    @api.constrains('einv_ap_journal_id')
    def _check_einv_ap_journal(self):
        """A vendor bill can only be booked in a purchase journal.

        Without this a bank or sale journal can be selected, and the failure
        only surfaces later as a rejected inbound document.
        """
        for company in self:
            journal = company.einv_ap_journal_id
            if not journal:
                continue
            if journal.type != 'purchase':
                raise ValidationError(_(
                    '"%(journal)s" is a %(type)s journal. The AP inbound journal '
                    'must be a purchase journal, because received supplier '
                    'documents are booked as vendor bills and vendor credit notes.',
                    journal=journal.display_name, type=journal.type))
            if journal.company_id != company:
                raise ValidationError(_(
                    '"%(journal)s" belongs to %(other)s, not to %(company)s.',
                    journal=journal.display_name, other=journal.company_id.display_name,
                    company=company.display_name))

    def einv_generate_ap_token(self):
        """Mint a fresh inbound webhook secret for this company."""
        self.ensure_one()
        self.sudo().einv_ap_token = 'odoo_ap_%s' % secrets.token_urlsafe(32)
        return True

    def _einv_api_url(self, path):
        """Join the configured base URL with an API path."""
        self.ensure_one()
        base = (self.einv_api_base_url or '').strip().rstrip('/')
        if not base:
            raise UserError(_(
                'No eInvoicing API base URL is configured for %s.', self.display_name))
        return '%s/%s' % (base, path.lstrip('/'))

    def _einv_get_ap_journal(self):
        """Purchase journal inbound documents are booked in.

        A configured journal is used only when it can actually hold a vendor
        bill. Anything else falls back to the company's first purchase journal
        rather than failing the delivery — a received Peppol document should
        never be lost to a configuration mistake.
        """
        self.ensure_one()
        configured = self.einv_ap_journal_id
        if configured and configured.type == 'purchase' \
                and configured.company_id == self:
            return configured
        if configured:
            _logger.warning(
                'eInvoice AP: %s is configured with journal "%s" (type %s, '
                'company %s), which cannot hold a vendor bill — falling back to '
                'the first purchase journal.',
                self.display_name, configured.display_name, configured.type,
                configured.company_id.display_name)
        return self.env['account.journal'].search(
            [('type', '=', 'purchase'), ('company_id', '=', self.id)], limit=1)

    @api.model
    def _einv_find_by_ap_payload(self, payload):
        """Resolve which company an inbound webhook body belongs to.

        Matched, in order, on the KGRN entity id, the entity TRN and the entity
        Peppol id — the three identifiers the payload carries in ``entity{}``.
        Falls back to the only AP-enabled company when there is exactly one.
        """
        entity = (payload or {}).get('entity') or {}
        companies = self.sudo().search([('einv_ap_enabled', '=', True)])
        if not companies:
            return self.browse()

        entity_id = (entity.get('id') or '').strip()
        if entity_id:
            match = companies.filtered(lambda c: (c.einv_entity_id or '').strip() == entity_id)
            if match:
                return match[0]

        trn = (entity.get('trn') or '').strip()
        if trn:
            match = companies.filtered(
                lambda c: (c.einv_entity_trn or '').strip() == trn
                or (c.vat or '').replace(' ', '') == trn)
            if match:
                return match[0]

        peppol_id = (entity.get('peppolId') or '').strip()
        if peppol_id:
            bare = peppol_id.split(':')[-1]
            match = companies.filtered(
                lambda c: (c.einv_peppol_sender_id or '').split(':')[-1] == bare)
            if match:
                return match[0]

        return companies[0] if len(companies) == 1 else self.browse()

    # ------------------------------------------------------------------
    # Platform calls
    # ------------------------------------------------------------------
    def action_einv_whoami(self):
        """Confirm which entity + location the token maps to.

        The documented smoke test: it catches a token pasted into the wrong
        environment before any mapping code runs.
        """
        self.ensure_one()
        token = self.sudo().einv_api_token
        if not token:
            raise UserError(_('No outbound API token is configured for %s.',
                              self.display_name))
        url = self._einv_api_url('external/outbound/whoami')
        status, body, error = self.env['einvoice.api']._request(
            'GET', url, token=token, timeout=self.einv_timeout or 60)

        if error is not None:
            message = error
            ok = False
        elif status == 200 and isinstance(body, dict) and body.get('entity'):
            entity = body.get('entity') or {}
            location = body.get('location') or {}
            token_info = body.get('token') or {}
            self.sudo().write({
                'einv_entity_id': entity.get('id') or self.einv_entity_id,
                'einv_entity_name': entity.get('name'),
                'einv_entity_trn': entity.get('trn'),
                'einv_peppol_sender_id': entity.get('peppolSenderId'),
                'einv_location_id': location.get('id') or self.einv_location_id,
                'einv_location_name': location.get('name'),
                'einv_token_name': token_info.get('name') or self.einv_token_name,
            })
            ok = True
            message = _('Connected as %(entity)s (TRN %(trn)s), location %(loc)s.',
                        entity=entity.get('name') or '?', trn=entity.get('trn') or '?',
                        loc=location.get('name') or _('unscoped'))
        else:
            ok = False
            message = (body or {}).get('error') or _('HTTP %s from the platform.', status)

        self.sudo().write({
            'einv_connection_state': 'ok' if ok else 'error',
            'einv_connection_message': message,
        })
        self.env['einvoice.log']._log({
            'company_id': self.id,
            'direction': 'ar',
            'operation': 'whoami',
            'endpoint': url,
            'http_status': status,
            'success': ok,
            'message': message,
            'response_body': body if error is None else error,
        })
        if not ok:
            raise UserError(_('eInvoicing connection failed:\n\n%s') % message)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Connection OK'), 'message': message,
                       'type': 'success', 'sticky': False},
        }

    @api.model
    def _einv_cron_check_token_expiry(self):
        """Warn before a token expires, so it can be rotated without a gap.

        Rotation order matters: issue the new token, switch Odoo over, then
        revoke the old one.
        """
        horizon = fields.Datetime.now() + relativedelta(days=14)
        companies = self.search([
            ('einv_enabled', '=', True),
            ('einv_token_expiry', '!=', False),
            ('einv_token_expiry', '<=', horizon),
        ])
        group = self.env.ref(
            'einvoicing_extended_rk.group_einvoicing_manager', raise_if_not_found=False)
        recipients = group.users if group else self.env['res.users'].browse()
        for company in companies:
            expired = company.einv_token_expiry <= fields.Datetime.now()
            body = _(
                'The KGRN eInvoicing API token for %(company)s %(verb)s on '
                '%(date)s. Issue the new token, switch Odoo over, then revoke '
                'the old one — in that order, to avoid a gap.',
                company=company.display_name,
                verb=_('expired') if expired else _('expires'),
                date=company.einv_token_expiry,
            )
            _logger.warning('eInvoice: token for %s %s on %s',
                            company.name, 'expired' if expired else 'expires',
                            company.einv_token_expiry)
            # res.company carries no activity mixin, so the alert goes out as
            # mail rather than as an activity on the company record.
            emails = [
                user.email for user in recipients
                if user.email and (not user.company_ids or company in user.company_ids)
            ]
            if not emails:
                continue
            self.env['mail.mail'].sudo().create({
                'subject': _('eInvoicing API token %(verb)s — %(company)s',
                             verb=_('has expired') if expired else _('expires soon'),
                             company=company.display_name),
                'body_html': '<p>%s</p>' % body,
                'email_to': ','.join(emails),
                'auto_delete': True,
            })
        return True
