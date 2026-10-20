# -*- coding: utf-8 -*-
"""Proposal and Service Engagement PDFs rendered by the KGRN eInvoicing PDF API.

The Node service (/home/Einvoicing Proposal) owns the document design and its
wording; Odoo only sends the client, the entities and the fees as JSON. Its URL
and API key are set in Settings → CRM → Proposal PDF API.

The API knows four fixed services. Quotations raised from now on use the four
products carrying `einv_pdf_service`; the older S1-S8 catalogue products are
archived, but orders that already hold them still print, each code folded into
one of the four. The fee of a service is the sum of its
order lines. Everything else the documents print (KGRN details, agreement
terms, support model, escalation, contacts, data protection) is left to the
API's own static defaults in config/document-defaults.json.
"""
import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PDF_API_URL_PARAM = 'proposal_workflow_extended_rk.pdf_api_url'
PDF_API_KEY_PARAM = 'proposal_workflow_extended_rk.pdf_api_key'
# A render takes 2-3 s, but the API queues requests beyond three at a time.
PDF_API_TIMEOUT = 120

# Retired S1-S8 catalogue, kept so orders raised before the switch still print.
# API service numbers: 1 Business Readiness & Gap Analysis, 2 Onboarding & ASP
# Linking, 3 ERP Development & Integration, 4 Annual Subscription & Support.
LEGACY_SERVICE_BY_CODE = {
    'S1': 1,   # Readiness Assessment / Gap Analysis
    'S2': 1,   # Data Readiness & Remediation Support
    'S3': 2,   # Standard Entity Onboarding
    'S4': 2,   # Standard Implementation
    'S5': 3,   # Extended Technical / API Integration
    'S6': 4,   # Annual ASP / Subscription Service
    'S7A': 4,  # Standard Support
    'S7B': 4,  # Extended Support
    'S8': 4,   # Managed Services
}


def _clip(value, size):
    """Trim to the API's field length; empty becomes False, which it drops."""
    value = (value or '').strip()
    return value[:size] if value else False


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('order_line.product_id.einv_pdf_service')
    def _compute_has_asp_subscription(self):
        """crm_extended_rk recognises the subscription by the retired [S6] code;
        Service 4 (the new S4, Annual Subscription & Support) succeeds it, so
        the overage rate applies to it too. Old orders holding S6 keep theirs."""
        super()._compute_has_asp_subscription()
        for order in self.filtered(lambda o: not o.has_asp_subscription):
            order.has_asp_subscription = any(
                line.product_id.einv_pdf_service == '4'
                for line in order.order_line
                if not line.display_type and line.product_id)

    # ── services and fees ─────────────────────────────────────────────────
    def _pdf_api_service_number(self, product):
        if product.einv_pdf_service:
            return int(product.einv_pdf_service)
        return LEGACY_SERVICE_BY_CODE.get((product.default_code or '').strip().upper())

    def _pdf_api_fees(self):
        """{service number: fee excl. VAT} from the order lines.

        Refuses a quotation the API cannot describe in full: one with no
        eInvoicing service, one carrying any other product (it would silently
        drop out of the fee table and the totals), or one not priced in AED,
        the only currency the documents print.
        """
        self.ensure_one()
        if self.currency_id.name != 'AED':
            raise UserError(_(
                "The proposal documents are priced in AED, but this quotation is "
                "in %s.", self.currency_id.name))
        fees, unmapped = {}, []
        for line in self.order_line:
            if line.display_type or not line.product_id:
                continue
            number = self._pdf_api_service_number(line.product_id)
            if not number:
                unmapped.append(line.product_id.display_name)
                continue
            fees[number] = fees.get(number, 0.0) + line.price_subtotal
        if unmapped:
            raise UserError(_(
                "These products are not eInvoicing services, so they cannot be "
                "printed in the proposal documents:\n\n%(products)s\n\n"
                "Remove them from this quotation, or quote them separately. "
                "The eInvoicing services are:\n%(services)s",
                products='\n'.join('• %s' % name for name in unmapped),
                services=self.env['product.template']._einv_pdf_service_list()))
        if not fees:
            raise UserError(_(
                "Add at least one eInvoicing service to this quotation before "
                "downloading the document:\n%s",
                self.env['product.template']._einv_pdf_service_list()))
        return fees

    def _pdf_api_fee_values(self, fees):
        values = {'service_%d' % number: round(amount, 2) for number, amount in fees.items()}
        # An unpriced ERP integration prints "To be quoted" rather than AED 0.
        if 3 in fees and not fees[3]:
            values['service_3'] = None
        return values

    # ── entities ──────────────────────────────────────────────────────────
    @api.model
    def _pdf_api_entity_has_data(self, entity):
        """Number of Entities sizes the Entities tab, so it routinely holds rows
        nobody has filled in; a row counts the moment it carries anything. A
        stated count of 0 is data, which is why the `*_count_set` flags are
        read rather than the integers."""
        return bool(
            (entity.name or '').strip()
            or entity.inbound_count_set
            or entity.outbound_count_set
            or entity.service_ids
            or entity.price
        )

    def _pdf_api_entities(self, fees, client_name):
        """The entity list, sized and priced the way the API validates it.

        Uses the Entities tab rows that carry anything; a quotation with none
        sends one entity under the client's name carrying the Total line's
        counts. With Service 4 (annual subscription & support) the counts set
        the agreed volume and the entity fees must add up to that service's
        fee, so both are checked here, where the salesperson can be told which
        field to fix.
        """
        self.ensure_one()
        subscription = 4 in fees
        selected = sorted(fees)
        rows = self.entity_ids.filtered(self._pdf_api_entity_has_data)

        entities, missing_counts = [], []
        for index, entity in enumerate(rows, start=1):
            name = (entity.name or '').strip() or 'Entity %d (to be confirmed)' % index
            numbers = sorted({
                number for number in map(self._pdf_api_service_number, entity.service_ids)
                if number
            }) or selected
            if subscription and not (entity.inbound_count_set and entity.outbound_count_set):
                missing_counts.append(name)
            entities.append({
                'name': name[:100],
                'short_name': name[:30],
                'inbound_invoices': entity.inbound_invoice_count if entity.inbound_count_set else 0,
                'outbound_invoices': entity.outbound_invoice_count if entity.outbound_count_set else 0,
                'services_label': ', '.join(map(str, numbers))[:40],
                'fee': round(entity.price, 2) if entity.price else None,
            })
        if not entities:
            if subscription and not (self.entity_inbound_total_set and self.entity_outbound_total_set):
                missing_counts.append(_("the Total line of the Entities tab"))
            entities.append({
                'name': client_name[:100],
                'short_name': client_name[:30],
                'inbound_invoices': self.entity_inbound_total if self.entity_inbound_total_set else 0,
                'outbound_invoices': self.entity_outbound_total if self.entity_outbound_total_set else 0,
                'services_label': ', '.join(map(str, selected)),
                'fee': None,
            })

        if missing_counts:
            raise UserError(_(
                "This quotation includes the annual subscription & support service, "
                "so the document states the agreed annual invoice volume. Enter the "
                "Annual Inbound and Annual Outbound invoice counts for:\n\n%s",
                '\n'.join('• %s' % name for name in missing_counts)))

        if subscription:
            subscription_fee = round(fees[4], 2)
            if len(entities) == 1:
                entities[0]['fee'] = subscription_fee
            else:
                entity_total = round(sum(entity['fee'] or 0.0 for entity in entities), 2)
                if abs(entity_total - subscription_fee) >= 0.005:
                    raise UserError(_(
                        "The document splits the annual subscription & support fee "
                        "across the entities, so the entity prices must add up to it.\n\n"
                        "Annual subscription & support lines: AED %(fee)s\n"
                        "Entity prices on the Entities tab: AED %(total)s\n\n"
                        "Adjust the entity prices so they total AED %(fee)s.",
                        fee='{:,.2f}'.format(subscription_fee),
                        total='{:,.2f}'.format(entity_total)))
                for entity in entities:
                    entity['fee'] = entity['fee'] or 0.0
        return entities

    # ── client ────────────────────────────────────────────────────────────
    def _pdf_api_client(self):
        self.ensure_one()
        partner = self.partner_id
        company = partner.commercial_partner_id
        # Only the addressee's name and title are read off the pipeline record,
        # and not every salesperson who may print the quotation can read it.
        lead = (self.crm_pipeline_id or self.opportunity_id).sudo()
        if partner != company or not partner.is_company:
            contact_name, designation = partner.name, partner.function
        else:
            contact_name, designation = lead.contact_name, lead.function
        address = '\n'.join(
            line.strip() for line in
            (company._display_address(without_company=True) or '').splitlines()
            if line.strip())
        client_name = company.name or partner.name or ''
        return {
            'name': _clip(client_name, 120),
            'contact_name': _clip(contact_name, 80) or _clip(client_name, 80),
            'contact_designation': _clip(designation, 80),
            'address': _clip(address, 300),
        }

    def _pdf_api_subscription(self):
        # An untyped rate is left to the API's default.
        if self.einv_overage_per_1000 > 0:
            return {'overage_rate_per_1000': round(self.einv_overage_per_1000, 2)}
        return False

    def _pdf_api_salesperson(self):
        """The Contact block on the last page of both documents."""
        user = self.user_id
        if not user:
            return False
        return {'name': _clip(user.name, 80), 'email': _clip(user.email, 120)}

    def _pdf_api_local_date(self, value):
        return fields.Datetime.context_timestamp(self, value).date() if value else False

    # ── payloads ──────────────────────────────────────────────────────────
    def _pdf_api_proposal_payload(self):
        self.ensure_one()
        fees = self._pdf_api_fees()
        client = self._pdf_api_client()
        issued = self._pdf_api_local_date(self.date_order) or fields.Date.context_today(self)
        valid_until = self.validity_date if self.validity_date and self.validity_date >= issued else False
        return {
            'client': client,
            'proposal': {
                'reference': self.name[:40],
                'date': str(issued),
                'valid_until': str(valid_until) if valid_until else False,
            },
            'entities': self._pdf_api_entities(fees, client['name']),
            'fees': self._pdf_api_fee_values(fees),
            'subscription': self._pdf_api_subscription(),
            'salesperson': self._pdf_api_salesperson(),
            'services_selected': sorted(fees),
        }

    def _pdf_api_service_engagement_payload(self):
        self.ensure_one()
        fees = self._pdf_api_fees()
        client = self._pdf_api_client()
        company = self.partner_id.commercial_partner_id
        trade_licence = (
            'einv_trade_license' in company._fields and company.einv_trade_license
        ) or company.company_license_no
        client.update({
            'legal_name': _clip(company.name, 160),
            'trn': _clip(company.vat, 20),
            'trade_licence': _clip(trade_licence, 120),
            'notice_details': _clip(', '.join(filter(None, (company.email, company.phone))), 160),
            'po_reference': _clip(self.client_order_ref, 60),
        })
        # Approval renames the quotation S07913 -> SE07913; the proposal it
        # follows went out under the S number.
        proposal_date = (
            self._pdf_api_local_date(self.proposal_generated_on)
            or self._pdf_api_local_date(self.date_order)
            or fields.Date.context_today(self))
        return {
            'client': client,
            'engagement': {
                'reference': self.name[:40],
                'effective_date': str(self.se_effective_date or fields.Date.context_today(self)),
            },
            'proposal': {
                'reference': re.sub(r'^SE(?=\d)', 'S', self.name)[:40],
                'date': str(proposal_date),
            },
            'entities': self._pdf_api_entities(fees, client['name']),
            'fees': self._pdf_api_fee_values(fees),
            'subscription': self._pdf_api_subscription(),
            'salesperson': self._pdf_api_salesperson(),
            'services_selected': sorted(fees),
        }

    # ── transport ─────────────────────────────────────────────────────────
    def _pdf_api_post(self, url, base_url, api_key, payload):
        try:
            response = requests.post(
                url, params={'format': 'base64'}, json=payload,
                headers={'X-API-Key': api_key}, timeout=PDF_API_TIMEOUT)
        except requests.RequestException as error:
            _logger.warning("Proposal PDF API unreachable at %s: %s", url, error)
            raise UserError(_(
                "The proposal PDF service at %(url)s could not be reached. "
                "Check that it is running and that the URL in Settings is right.\n\n%(error)s",
                url=base_url, error=error))
        try:
            body = response.json()
        except ValueError:
            body = {}
        return response, body if isinstance(body, dict) else {}

    def _pdf_api_render(self, document_type, payload):
        """POST the payload and return the PDF base64-encoded, ready for
        ir.attachment.datas."""
        params = self.env['ir.config_parameter'].sudo()
        base_url = (params.get_param(PDF_API_URL_PARAM) or '').strip().rstrip('/')
        api_key = (params.get_param(PDF_API_KEY_PARAM) or '').strip()
        if not base_url or not api_key:
            raise UserError(_(
                "The proposal PDF service is not configured. An administrator must "
                "set its URL and API key in Settings → CRM → Proposal PDF API."))

        url = '%s/api/v1/%s' % (base_url, document_type)
        response, body = self._pdf_api_post(url, base_url, api_key, payload)
        # An API deployment older than the salesperson Contact block rejects the
        # field it does not know; the document still renders without it.
        if response.status_code == 400 and payload.get('salesperson') and all(
                (detail.get('field') or '').startswith('salesperson')
                for detail in (body.get('error') or {}).get('details') or [{}]):
            _logger.warning("Proposal PDF API at %s does not accept 'salesperson'; "
                            "rendering without the Contact details", base_url)
            payload = dict(payload, salesperson=False)
            response, body = self._pdf_api_post(url, base_url, api_key, payload)

        if response.status_code == 200 and body.get('success') and body.get('data'):
            return body['data']

        error = body.get('error') or {}
        _logger.warning("Proposal PDF API %s for %s %s: %s",
                        response.status_code, document_type, self.name, error or response.text[:500])
        if response.status_code == 401:
            raise UserError(_(
                "The proposal PDF service rejected the API key. Update it in "
                "Settings → CRM → Proposal PDF API."))
        details = '\n'.join(
            '• %s: %s' % (detail.get('field'), detail.get('message'))
            for detail in error.get('details') or [])
        raise UserError(_(
            "The proposal PDF service could not generate the document (HTTP %(status)s).\n\n"
            "%(message)s\n%(details)s",
            status=response.status_code,
            message=error.get('message') or response.text[:500],
            details=details))

