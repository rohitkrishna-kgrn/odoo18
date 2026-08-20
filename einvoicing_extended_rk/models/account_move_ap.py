# -*- coding: utf-8 -*-
"""AP inbound — turn a document pushed by the platform into an Odoo bill.

The platform POSTs ``{event, receivedAt, entity{}, document{...data{}}}`` to the
configured webhook; ``document.data`` is the complete parsed PINT-AE field map.
Two events matter:

* ``ap.invoice.received``     — UBL ``Invoice``    (type codes 380 / 389) -> Vendor Bill
* ``ap.credit_note.received`` — UBL ``CreditNote`` (type codes 381 / 261) -> Vendor Credit Note

The event, not the numeric type code, decides invoice vs credit note: 380 and
389 are both UBL ``Invoice``, 381 and 261 are both UBL ``CreditNote``.

Delivery is idempotency-keyed on ``document.instanceId``, and the platform
retries once on a 5xx — so the same instance id must upsert, never duplicate.
"""
import base64
import json
import logging

from odoo import _, api, fields, models

from . import einvoice_lookups as lk

_logger = logging.getLogger(__name__)


class EinvoiceRejected(Exception):
    """A received document a retry could not fix — answered with a 4xx.

    Distinct from an unexpected failure, which must answer 5xx so the platform
    spends its one retry on it.
    """


# event name -> (Odoo move type, docType we expect alongside it)
AP_EVENT_MOVE_TYPE = {
    'ap.invoice.received': 'in_invoice',
    'ap.credit_note.received': 'in_refund',
}


class AccountMoveAp(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def _einv_receive_document(self, payload, company):
        """Create or update the Odoo document for one inbound webhook body.

        Returns ``(move, action)`` where action is ``created``, ``updated`` or
        ``unchanged``. Raises nothing the caller cannot map onto an HTTP status.
        """
        event = payload.get('event')
        move_type = AP_EVENT_MOVE_TYPE.get(event)
        if not move_type:
            raise EinvoiceRejected(_('Unsupported event "%s".', event))

        document = payload.get('document') or {}
        data = document.get('data') or {}
        instance_id = (document.get('instanceId')
                       or data.get('__instanceId') or '').strip()

        existing = self._einv_find_received(instance_id, document, company)
        if existing:
            # The platform retries once on a 5xx and re-pushes from the portal,
            # so a repeat is normal. A posted bill is never rewritten.
            if existing.state != 'draft':
                _logger.info(
                    'eInvoice AP: %s already received as %s (posted) — ignored.',
                    instance_id, existing.name)
                return existing, 'unchanged'
            existing._einv_apply_inbound(payload, company)
            return existing, 'updated'

        move = self.sudo().with_company(company).create(
            self._einv_inbound_values(payload, company, move_type))
        move._einv_apply_inbound(payload, company, skip_header=True)
        return move, 'created'

    @api.model
    def _einv_find_received(self, instance_id, document, company):
        """Find a document already received for this instance id.

        Falls back to the supplier document number for the case where the
        platform re-sends the same bill under a new instance id (a re-push from
        the portal), which would otherwise duplicate the vendor bill.
        """
        Move = self.sudo().with_context(active_test=False)
        if instance_id:
            found = Move.search([
                ('einv_instance_id', '=', instance_id),
                ('company_id', '=', company.id),
            ], limit=1)
            if found:
                return found
        doc_id = (document.get('id') or '').strip()
        sender = (document.get('senderId') or '').strip()
        if doc_id and sender:
            return Move.search([
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('company_id', '=', company.id),
                ('ref', '=', doc_id),
                ('einv_sender_id', '=', sender),
            ], limit=1)
        return Move.browse()

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    @api.model
    def _einv_inbound_values(self, payload, company, move_type):
        """Values for creating the vendor bill / credit note."""
        document = payload.get('document') or {}
        data = document.get('data') or {}
        journal = company._einv_get_ap_journal()
        partner = self._einv_resolve_vendor(data, document, company)
        currency = self._einv_resolve_currency(data, document, company)

        vals = {
            'move_type': move_type,
            'company_id': company.id,
            'journal_id': journal.id if journal else False,
            'partner_id': partner.id if partner else False,
            'currency_id': currency.id,
            'ref': document.get('id') or data.get('InvoiceID') or '',
            'invoice_date': self._einv_parse_date(
                data.get('IssueDate') or document.get('issueDate')),
            'invoice_date_due': self._einv_parse_date(data.get('DueDate')),
            'einv_state': 'received',
            'einv_direction': 'ap',
        }
        if not vals['journal_id']:
            raise EinvoiceRejected(_(
                '%s has no purchase journal, so a vendor bill cannot be created. '
                'Set one under Settings > Accounting > KGRN eInvoicing - AP '
                'inbound > AP Journal.', company.display_name))
        return vals

    def _einv_apply_inbound(self, payload, company, skip_header=False):
        """Write the full PINT-AE field map onto an existing draft."""
        self.ensure_one()
        document = payload.get('document') or {}
        data = document.get('data') or {}
        type_code = str(data.get('InvoiceTypeCode') or '380')

        vals = {
            'einv_instance_id': document.get('instanceId') or data.get('__instanceId') or False,
            'einv_sender_id': document.get('senderId') or data.get('__senderId') or False,
            'einv_receiver_id': document.get('receiverId') or data.get('__receiverId') or False,
            'einv_record_id': document.get('recordId') or False,
            'einv_received_date': self._einv_parse_datetime(payload.get('receivedAt')),
            'einv_state': 'received',
            'einv_payload': json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            'einv_message': _('Received from the KGRN eInvoicing platform.'),
            # 389 / 261 are the self-billed pair.
            'einv_self_billed': type_code in lk.SELF_BILLED_TYPE_CODES,
            'einv_invoice_type_code': (
                type_code if type_code in dict(lk.INVOICE_TYPE_CODES) else False),
            'einv_unique_invoice_number': (
                document.get('instanceId') or data.get('InvoiceID') or False),
        }
        if not skip_header:
            partner = self._einv_resolve_vendor(data, document, company)
            if partner:
                vals['partner_id'] = partner.id
            vals['ref'] = document.get('id') or data.get('InvoiceID') or self.ref
            issue_date = self._einv_parse_date(
                data.get('IssueDate') or document.get('issueDate'))
            if issue_date:
                vals['invoice_date'] = issue_date
            due_date = self._einv_parse_date(data.get('DueDate'))
            if due_date:
                vals['invoice_date_due'] = due_date
            currency = self._einv_resolve_currency(data, document, company)
            if currency and currency != self.currency_id:
                vals['currency_id'] = currency.id

        # Cross-currency: only meaningful when it differs from the document
        # currency, which is the same condition the platform applies (ibr-077).
        vat_currency_code = (data.get('VATCurrencyCode') or '').upper()
        if vat_currency_code and vat_currency_code != (
                data.get('DocumentCurrencyCode') or '').upper():
            vat_currency = self.env['res.currency'].with_context(
                active_test=False).search([('name', '=', vat_currency_code)], limit=1)
            vals['einv_vat_currency_id'] = vat_currency.id if vat_currency else False
        else:
            vals['einv_vat_currency_id'] = False

        vals.update(self._einv_inbound_header_fields(data))
        self.sudo().write(vals)

        self._einv_rebuild_inbound_lines(data, company)
        self._einv_store_inbound_allowances(data)
        self._einv_store_inbound_attachments(document, data, company)

        if company.einv_ap_auto_post and self.state == 'draft':
            try:
                self.sudo().action_post()
            except Exception as exc:
                # Auto-posting is a convenience; a bill that cannot post yet
                # (missing account, unbalanced tax) still has to be kept.
                _logger.warning('eInvoice AP: could not auto-post %s: %s', self.name, exc)
                self.sudo().message_post(body=_(
                    'eInvoicing: the document was received but could not be '
                    'posted automatically — %s', exc))
        return True

    @api.model
    def _einv_inbound_header_fields(self, data):
        """Map the received header fields onto the eInvoice fields."""
        vals = {
            'einv_issue_time': data.get('IssueTime') or False,
            'einv_financial_year': data.get('FinancialYear') or False,
            'einv_reference_number': data.get('ReferenceNumber') or False,
            'einv_buyer_reference': data.get('BuyerReference') or False,
            'einv_buyer_accounting_reference': data.get('BuyerAccountingReference') or False,
            'einv_principle_id': data.get('PrincipleID') or False,
            'einv_beneficiary_id': data.get('BeneficiaryID') or False,
            'einv_note': (data.get('Note') or '')[:300] or False,
            'einv_po_reference': data.get('Purchaseorderreference') or False,
            'einv_so_reference': data.get('Salesorderreference') or False,
            'einv_despatch_advice_ref': data.get('Despatchadvicereference') or False,
            'einv_receiving_advice_ref': data.get('Receivingadvicereference') or False,
            'einv_customs_ref': data.get('Customsreferencenumber') or False,
            'einv_preceding_invoice_number': data.get('PrecedingInvoiceNumber') or False,
            'einv_lot_reference': data.get('LotReference') or False,
            'einv_project_reference': data.get('ProjectReference') or False,
            'einv_contract_reference': data.get('ContractReference') or False,
            'einv_contract_value': data.get('ContractValue') or False,
            'einv_additional_doc_ref_id': data.get('AdditionalDocumentReferenceID') or False,
            'einv_additional_doc_scheme_id': data.get('AdditionalDocSchemeID') or False,
            'einv_document_type_code': data.get('DocumentTypecode') or False,
            'einv_document_description': data.get('DocumentDescription') or False,
            'einv_external_reference_id': data.get('ExternalReferenceID') or False,
            'einv_deliver_to_location_id': data.get('DeliverToLocationIdentifier') or False,
            'einv_deliver_to_location_scheme': data.get('DeliverToLocationSchemeID') or False,
            'einv_payee_name': data.get('PayeeName') or False,
            'einv_payment_instructions': data.get('PaymentInstructions') or False,
            'einv_payment_network_id': data.get('PaymentNetworkId') or False,
            'einv_card_holder_name': data.get('PaymentCardHolderName') or False,
            'einv_card_pan': data.get('PaymentCardPAN') or False,
            'einv_payment_terms_text': data.get('PaymentTerms') or False,
            'einv_payee_account_id': data.get('PayeeAccountID') or False,
            'einv_payee_account_name': data.get('PayeeAccountName') or False,
            'einv_payee_identifier': data.get('PayeeIdentifier') or False,
            'einv_payee_legal_reg_id': data.get('PayeeLegalRegistrationIdentifier') or False,
        }
        # Selection fields only accept a value that is in their list.
        for key, field_name, allowed in (
            ('InvoiceTransactionTypeCode', 'einv_transaction_type_code',
             dict(lk.TRANSACTION_TYPE_CODES)),
            ('PaymentMeansCode', 'einv_payment_means_code', dict(lk.PAYMENT_MEANS_CODES)),
            ('Creditnotereasoncode', 'einv_credit_note_reason_code',
             dict(lk.CREDIT_NOTE_REASON_CODES)),
            ('FrequencyofBilling', 'einv_billing_frequency', dict(lk.BILLING_FREQUENCY_CODES)),
        ):
            value = data.get(key)
            vals[field_name] = value if value in allowed else False

        for key, field_name in (('VATtaxpointdate', 'einv_vat_taxpoint_date'),
                                ('InvoicePeriodStartDate', 'einv_period_start'),
                                ('InvoicePeriodEndDate', 'einv_period_end'),
                                ('PrecedingInvoiceIssueDate', 'einv_preceding_invoice_date'),
                                ('ActualDeliveryDate', 'einv_actual_delivery_date')):
            vals[field_name] = self._einv_parse_date(data.get(key)) or False

        # The party blocks the platform delivered, kept verbatim: the supplier
        # master data in Odoo may differ from what the supplier actually
        # transmitted, and the document has to show what was received.
        legal_types = dict(lk.LEGAL_REG_TYPE_CODES)
        seller_type = data.get('SellerLegalRegistrationType')
        buyer_type = data.get('Buyerlegalregistrationidentifiertype')
        vals.update({
            'einv_seller_name': data.get('SellerName') or False,
            'einv_seller_trn': data.get('SellerTaxidentifier') or False,
            'einv_seller_electronic_address': data.get('SellerElectronicAddress') or False,
            'einv_seller_scheme_id': data.get('SellerSchemeidentifier') or False,
            'einv_seller_legal_reg_type': seller_type if seller_type in legal_types else False,
            'einv_seller_legal_reg_id': data.get('SellerLegalRegistrationIdentifier') or False,
            'einv_seller_trade_license': data.get('SellerCommercialTradelicense') or False,
            'einv_seller_authority_name': data.get('SellerAuthorityname') or False,
            'einv_seller_address1': data.get('SellerAddressLine1') or False,
            'einv_seller_address2': data.get('SellerAddressLine2') or False,
            'einv_seller_city': data.get('SellerCity') or False,
            'einv_seller_country_subdivision': data.get('SellerCountrySubdivision') or False,
            'einv_seller_postal_zone': data.get('SellerPostalZone') or False,
            'einv_seller_country_code': data.get('SellerCountryCode') or False,
            'einv_seller_contact_point': data.get('SellerContactPoint') or False,
            'einv_seller_phone': data.get('SellerContactTelephone') or False,
            'einv_seller_email': data.get('SellerEmail') or False,
            'einv_buyer_name': data.get('BuyerName') or False,
            'einv_buyer_vat': data.get('BuyerVatIdentifier') or False,
            'einv_buyer_identifier': data.get('BuyerIdentifier') or False,
            'einv_buyer_electronic_address': data.get('BuyerElectronicAddress') or False,
            'einv_buyer_scheme_id': data.get('BuyerSchemeidentifier') or False,
            'einv_buyer_email': data.get('BuyerEmail') or False,
            'einv_buyer_contact_point': data.get('BuyerContactPoint') or False,
            'einv_buyer_phone': data.get('BuyerContactTelephone') or False,
            'einv_buyer_address1': data.get('BuyerAddressLine1') or False,
            'einv_buyer_address2': data.get('BuyerAddressLine2') or False,
            'einv_buyer_city': data.get('BuyerCity') or False,
            'einv_buyer_country_subdivision': data.get('BuyerCountrySubdivision') or False,
            'einv_buyer_postal_zone': data.get('BuyerPostalZone') or False,
            'einv_buyer_country_code': data.get('BuyerCountryCode') or False,
            'einv_buyer_legal_reg_type': buyer_type if buyer_type in legal_types else False,
            'einv_buyer_legal_reg_id': data.get('BuyerLegalRegistrationIdentifier') or False,
            'einv_buyer_trade_license': data.get('BuyerCommercialorTradelicense') or False,
            'einv_buyer_emirates_id': data.get('BuyerEmiratesID') or False,
            'einv_buyer_passport': data.get('BuyerPassport') or False,
            'einv_buyer_passport_country': data.get('BuyerPassportIssuingCountrycode') or False,
            'einv_buyer_cabinet_decision': data.get('BuyerCabinetDecision') or False,
            'einv_buyer_authority_name': data.get('BuyerAuthorityName') or False,
            'einv_delivery_party_name': data.get('DeliverToPartyName') or False,
            'einv_delivery_address1': data.get('DeliverToAddressLine1') or False,
            'einv_delivery_address2': data.get('DeliverToAddressLine2') or False,
            'einv_delivery_city': data.get('DeliverToCity') or False,
            'einv_delivery_country_subdivision': data.get('DeliverToCountrySubdivision') or False,
            'einv_delivery_postal_zone': data.get('DeliverToPostalZone') or False,
            'einv_delivery_country_code': data.get('DeliverToCountryCode') or False,
            'einv_incoterms': data.get('Incoterms') or False,
        })

        vals['einv_prepaid_amount'] = self._einv_float(data.get('PrepaidAmount'))
        vals['einv_rounding_amount'] = self._einv_float(data.get('PayableRoundingAmount'))
        vals['einv_currency_exchange_rate'] = self._einv_float(
            data.get('CurrencyExchangeRate'))
        return vals

    # ------------------------------------------------------------------
    # Vendor / currency resolution
    # ------------------------------------------------------------------
    @api.model
    def _einv_resolve_vendor(self, data, document, company):
        """Find the supplier, matching on the strongest identifier first.

        Peppol id and TRN identify a legal entity exactly; the name does not,
        so it is only a last resort and only for an exact match.
        """
        Partner = self.env['res.partner'].sudo()
        trn = (data.get('SellerTaxidentifier') or '').replace(' ', '').strip()
        peppol = (data.get('SellerElectronicAddress')
                  or document.get('senderId') or '').strip()
        peppol_bare = peppol.split(':')[-1] if peppol else ''
        name = (data.get('SellerName') or document.get('seller') or '').strip()

        if peppol_bare:
            partner = Partner.search([
                '|', ('einv_peppol_id', '=', peppol_bare), ('peppol_endpoint', '=', peppol_bare),
            ], limit=1)
            if partner:
                return partner
        if trn:
            partner = Partner.search([('vat', 'in', (trn, ' '.join(trn)))], limit=1)
            if partner:
                return partner
        if name:
            partner = Partner.search([('name', '=ilike', name)], limit=1)
            if partner:
                return partner

        if not company.einv_ap_create_partner:
            return Partner.browse()
        if not name:
            return Partner.browse()
        return Partner.create(self._einv_vendor_values(data, peppol_bare, trn, name))

    @api.model
    def _einv_vendor_values(self, data, peppol_bare, trn, name):
        """Create the supplier from the seller block of the received document."""
        country = self.env['res.country'].search(
            [('code', '=', (data.get('SellerCountryCode') or 'AE').upper())], limit=1)
        state = self.env['res.country.state'].browse()
        subdivision = (data.get('SellerCountrySubdivision') or '').strip()
        if subdivision and country:
            state = self.env['res.country.state'].search([
                ('country_id', '=', country.id),
                '|', ('einv_emirate_code', '=', subdivision.upper()),
                '|', ('code', '=ilike', subdivision), ('name', '=ilike', subdivision),
            ], limit=1)
        return {
            'name': name,
            'company_type': 'company',
            'supplier_rank': 1,
            'vat': trn or False,
            'einv_peppol_id': peppol_bare or False,
            'einv_peppol_scheme': data.get('SellerSchemeidentifier') or '0235',
            'einv_legal_reg_id': data.get('SellerLegalRegistrationIdentifier') or False,
            'einv_trade_license': data.get('SellerCommercialTradelicense') or False,
            'einv_authority_name': data.get('SellerAuthorityname') or False,
            'street': data.get('SellerAddressLine1') or False,
            'street2': data.get('SellerAddressLine2') or False,
            'city': data.get('SellerCity') or False,
            'zip': data.get('SellerPostalZone') or False,
            'state_id': state.id if state else False,
            'country_id': country.id if country else False,
            'phone': data.get('SellerContactTelephone') or False,
            'email': data.get('SellerEmail') or False,
        }

    @api.model
    def _einv_resolve_currency(self, data, document, company):
        code = (data.get('DocumentCurrencyCode') or document.get('currency') or 'AED').upper()
        currency = self.env['res.currency'].with_context(active_test=False).search(
            [('name', '=', code)], limit=1)
        return currency or company.currency_id

    # ------------------------------------------------------------------
    # Lines
    # ------------------------------------------------------------------
    def _einv_rebuild_inbound_lines(self, data, company):
        """Replace the invoice lines with the received ``items[]``."""
        self.ensure_one()
        items = data.get('items') or []
        if not items:
            return
        commands = [(5, 0, 0)]
        for index, item in enumerate(items, start=1):
            commands.append((0, 0, self._einv_inbound_line_values(item, index, company)))
        self.sudo().write({'invoice_line_ids': commands})

    def _einv_inbound_line_values(self, item, index, company):
        """One received ``items[]`` entry as an Odoo invoice line."""
        self.ensure_one()
        product = self._einv_resolve_product(item, company)
        uom = self._einv_resolve_uom(item.get('unit'))
        vat_category = item.get('vatCategory') or 'S'
        vat_rate = self._einv_float(item.get('vatRate'))
        tax = self._einv_resolve_tax(vat_category, vat_rate, company)

        qty = self._einv_float(item.get('qty')) or 1.0
        unit_price = self._einv_float(item.get('unitPrice'))
        base_quantity = self._einv_float(item.get('baseQuantity')) or 1.0
        # Line net = qty x (unitPrice / baseQuantity); Odoo has no base
        # quantity, so it is folded into the unit price.
        if base_quantity and base_quantity != 1.0:
            unit_price = unit_price / base_quantity

        vals = {
            'name': item.get('description') or item.get('name') or _('Line %s', index),
            'quantity': qty,
            'price_unit': unit_price,
            'tax_ids': [(6, 0, tax.ids)],
            'einv_line_identifier': str(item.get('InvoiceLineIdentifier') or index),
            'einv_item_type': item.get('itemType') if item.get('itemType') in
                              dict(lk.ITEM_TYPE_CODES) else False,
            'einv_sac_code': item.get('serviceAccountingCode') or False,
            'einv_hs_code': item.get('itemClassification') or False,
            'einv_type_of_goods': item.get('typeOfGoods') or False,
            'einv_item_standard_id': item.get('itemStandardId') or False,
            'einv_buyer_item_id': item.get('buyerItemId') or False,
            'einv_seller_item_id': item.get('sellerItemId') or False,
            'einv_item_name': item.get('name') or False,
            'einv_attribute_name': item.get('attributeName') or False,
            'einv_attribute_value': item.get('attributeValue') or False,
            'einv_vat_category': vat_category if vat_category in
                                 dict(lk.VAT_CATEGORY_CODES) else 'S',
            'einv_vat_rate': vat_rate,
            'einv_tax_exemption_reason_code': item.get('taxExemptionReasonCode') or False,
            'einv_tax_exemption_reason': item.get('taxExemptionReason') or False,
            'einv_base_quantity': base_quantity,
            'einv_gross_price': self._einv_float(item.get('grossPrice')),
            'einv_price_discount': self._einv_float(item.get('priceDiscount')),
            'einv_order_line_id': item.get('orderLineId') or False,
        }
        if product:
            vals['product_id'] = product.id
        if uom:
            vals['product_uom_id'] = uom.id
        account = self._einv_resolve_account(product, company)
        if account:
            vals['account_id'] = account.id
        origin = (item.get('originCountry') or '').strip()
        if origin:
            country = self.env['res.country'].search([('code', '=', origin.upper())], limit=1)
            if country:
                vals['einv_origin_country_id'] = country.id
        return vals

    @api.model
    def _einv_resolve_product(self, item, company):
        """Match the received item onto a product, or fall back."""
        Product = self.env['product.product'].sudo()
        for domain in (
            [('default_code', '=', item.get('sellerItemId'))],
            [('default_code', '=', item.get('buyerItemId'))],
            [('barcode', '=', item.get('itemStandardId'))],
            [('name', '=ilike', item.get('name'))],
        ):
            if not domain[0][2]:
                continue
            product = Product.search(domain, limit=1)
            if product:
                return product
        return company.einv_ap_product_id

    @api.model
    def _einv_resolve_uom(self, unece_code):
        """Find the unit of measure for a UN/ECE Rec 20 code.

        C62 is the default on every unit that has not been mapped, so a plain
        search would return whichever record happens to come first. The
        canonical unit for a seeded code therefore wins outright, and only an
        unseeded code falls through to the search.
        """
        if not unece_code:
            return self.env['uom.uom'].browse()
        canonical = {v: k for k, v in reversed(lk.DEFAULT_UOM_UNECE_CODES.items())}
        xmlid = canonical.get(unece_code)
        if xmlid:
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom:
                return uom
        return self.env['uom.uom'].sudo().search(
            [('einv_unece_code', '=', unece_code)], limit=1, order='id')

    @api.model
    def _einv_resolve_tax(self, vat_category, vat_rate, company):
        """Find the purchase tax matching the received category and rate.

        Falls back to the configured tax so a bill is never silently created
        with no VAT at all — an inbound document is never rejected, so the
        difference has to be visible on the draft instead.
        """
        Tax = self.env['account.tax'].sudo()
        domain = [('type_tax_use', '=', 'purchase'), ('company_id', '=', company.id)]
        if vat_category in lk.VAT_TAXED_CATEGORIES:
            tax = Tax.search(domain + [
                ('einv_vat_category', '=', vat_category),
                ('amount_type', '=', 'percent'),
                ('amount', '=', vat_rate),
            ], limit=1)
            if tax:
                return tax
            tax = Tax.search(domain + [
                ('amount_type', '=', 'percent'), ('amount', '=', vat_rate)], limit=1)
            if tax:
                return tax
        else:
            tax = Tax.search(domain + [('einv_vat_category', '=', vat_category)], limit=1)
            if tax:
                return tax
            if not vat_rate:
                tax = Tax.search(domain + [('amount', '=', 0.0)], limit=1)
                if tax:
                    return tax
        return company.einv_ap_tax_id

    @api.model
    def _einv_resolve_account(self, product, company):
        if product:
            accounts = product.product_tmpl_id.get_product_accounts()
            if accounts.get('expense'):
                return accounts['expense']
        return company.einv_ap_account_id

    # ------------------------------------------------------------------
    # Allowances and attachments
    # ------------------------------------------------------------------
    def _einv_store_inbound_allowances(self, data):
        """Keep the received allowances / charges alongside the document."""
        self.ensure_one()
        Allowance = self.env['einvoice.allowance'].sudo()
        self.einv_allowance_ids.unlink()
        for entry in data.get('allowances') or []:
            Allowance.create(Allowance._einv_from_payload(entry, move=self))

        # Line allowances are matched back by line identifier.
        by_identifier = {l.einv_line_identifier: l for l in self.invoice_line_ids}
        for index, item in enumerate(data.get('items') or [], start=1):
            entries = item.get('allowances') or []
            if not entries:
                continue
            line = by_identifier.get(str(item.get('InvoiceLineIdentifier') or index))
            if not line:
                continue
            for entry in entries:
                Allowance.create(Allowance._einv_from_payload(entry, line=line))

    def _einv_store_inbound_attachments(self, document, data, company):
        """Attach the received files and, when sent, the raw UBL."""
        self.ensure_one()
        Attachment = self.env['ir.attachment'].sudo()
        for entry in data.get('attachments') or []:
            content = entry.get('base64')
            if not content:
                continue
            try:
                raw = base64.b64decode(content)
            except Exception:
                _logger.warning('eInvoice AP: undecodable attachment on %s', self.name)
                continue
            Attachment.create({
                'name': entry.get('fileName') or 'attachment',
                'datas': base64.b64encode(raw),
                'res_model': 'account.move',
                'res_id': self.id,
                'mimetype': entry.get('mimeCode') or 'application/octet-stream',
            })
        xml = document.get('xml')
        if xml and company.einv_ap_store_xml:
            Attachment.create({
                'name': '%s.xml' % (document.get('id') or 'peppol-document'),
                'datas': base64.b64encode(xml.encode()),
                'res_model': 'account.move',
                'res_id': self.id,
                'mimetype': 'application/xml',
            })

    # ------------------------------------------------------------------
    # Parsing helpers — everything inbound arrives as a string
    # ------------------------------------------------------------------
    @api.model
    def _einv_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _einv_parse_date(self, value):
        if not value:
            return False
        try:
            return fields.Date.to_date(str(value)[:10])
        except (ValueError, TypeError):
            return False

    @api.model
    def _einv_parse_datetime(self, value):
        if not value:
            return False
        try:
            return fields.Datetime.to_datetime(str(value).replace('Z', '').replace('T', ' ')[:19])
        except (ValueError, TypeError):
            return False
