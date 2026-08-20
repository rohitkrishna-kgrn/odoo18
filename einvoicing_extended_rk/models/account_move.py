# -*- coding: utf-8 -*-
import base64
import json
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_round

from . import einvoice_lookups as lk

_logger = logging.getLogger(__name__)

# Odoo move types that map onto an AR (outbound) document.
AR_TYPES = ('out_invoice', 'out_refund')
# ... and onto an AP (inbound) document.
AP_TYPES = ('in_invoice', 'in_refund')


class AccountMove(models.Model):
    """AR outbound push and AP inbound storage for the KGRN eInvoicing platform.

    The four platform document types map onto Odoo like this::

        380  Tax Invoice              AR  out_invoice   AP  in_invoice
        381  Credit Note              AR  out_refund    AP  in_refund
        389  Self-Billed Invoice      AR  out_invoice   AP  in_invoice
        261  Self-Billed Credit Note  AR  out_refund    AP  in_refund

    Direction decides which side of Odoo the document lives on; the
    ``Self-Billed`` flag decides between 380/389 and 381/261, because a
    self-billed document has exactly the same field shape as its ordinary
    counterpart — only the type code differs.
    """
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    einv_direction = fields.Selection(
        [('ar', 'AR — outbound'), ('ap', 'AP — inbound')],
        string='eInvoice Direction', compute='_compute_einv_direction', store=True)
    einv_applicable = fields.Boolean(
        string='eInvoicing Applicable', compute='_compute_einv_direction', store=True,
        help='True for customer invoices, customer credit notes, vendor bills '
             'and vendor credit notes of a company with eInvoicing enabled.')
    einv_self_billed = fields.Boolean(
        string='Self-Billed',
        help='A self-billed document is raised by the buyer on the supplier '
             "behalf. It switches the type code from 380 to 389 (invoice) or "
             'from 381 to 261 (credit note); the fields are otherwise identical.',
    )
    einv_invoice_type_code = fields.Selection(
        lk.INVOICE_TYPE_CODES, string='Invoice Type Code',
        compute='_compute_einv_invoice_type_code', store=True, readonly=False,
        help='PINT-AE document type. Derived from the Odoo document type and '
             'the Self-Billed flag; override only if the platform expects a '
             'different code.',
    )
    einv_unique_invoice_number = fields.Char(
        string='Unique Invoice Number', copy=False, index=True,
        compute='_compute_einv_unique_invoice_number', store=True, readonly=False,
        help='Idempotency key, unique per KGRN entity. Resending the same '
             'value updates the same platform record instead of creating a '
             'duplicate — never generate a new one for a retry.',
    )
    einv_push_state = fields.Selection(
        [('draft', 'Draft — store only'), ('submit', 'Submit — clear with the FTA')],
        string='Push Mode', compute='_compute_einv_push_state',
        store=True, readonly=False,
        help='What the next push attempts. Defaults to the company setting.',
    )

    # ------------------------------------------------------------------
    # Outcome
    # ------------------------------------------------------------------
    einv_state = fields.Selection(
        [('not_sent', 'Not sent'),
         ('draft', 'Draft on platform'),
         ('submitted', 'Submitted'),
         ('cleared', 'Cleared'),
         ('rejected', 'Rejected'),
         ('error', 'Error'),
         ('received', 'Received')],
        string='eInvoice Status', default='not_sent', copy=False, tracking=True, index=True,
        help='"Cleared" is only set when the platform reported success AND '
             'peppol.status SUCCESS — that is the FTA-cleared state.',
    )
    einv_record_id = fields.Char(
        string='Platform Record ID', copy=False, readonly=True,
        help='The platform invoice id — quote it in a support ticket.')
    einv_instance_id = fields.Char(
        string='Peppol Instance ID', copy=False, readonly=True, index=True,
        help='peppol.instanceIdentifier on AR, document.instanceId on AP. '
             'The reconciliation key, and the idempotency key inbound.')
    einv_request_id = fields.Char(string='Last Request ID', copy=False, readonly=True)
    einv_peppol_status = fields.Char(string='Peppol Status', copy=False, readonly=True)
    einv_platform_status = fields.Char(
        string='Platform Status', copy=False, readonly=True,
        help='The status the platform reports for its own record — draft, '
             'submitted, cleared or rejected. A validation failure leaves it a '
             'correctable draft there while the invoice shows as an error here.')
    einv_error_code = fields.Char(string='Last Error Code', copy=False, readonly=True)
    einv_message = fields.Text(string='Platform Message', copy=False, readonly=True)
    einv_last_push_date = fields.Datetime(string='Last Pushed On', copy=False, readonly=True)
    einv_received_date = fields.Datetime(string='Received On', copy=False, readonly=True)
    einv_error_ids = fields.One2many(
        'einvoice.error', 'move_id', string='Validation Errors', copy=False)
    einv_error_count = fields.Integer(
        string='Validation Error Count', compute='_compute_einv_error_count')
    einv_log_ids = fields.One2many('einvoice.log', 'move_id', string='Transmission Log')
    einv_log_count = fields.Integer(string='Log Count', compute='_compute_einv_log_count')
    einv_locked = fields.Boolean(
        string='Locked on Platform', compute='_compute_einv_locked',
        help='A submitted invoice cannot be overwritten with the same key.')

    # ------------------------------------------------------------------
    # Invoice details the platform needs and Odoo has no field for
    # ------------------------------------------------------------------
    einv_issue_time = fields.Char(
        string='Issue Time', help='HH:MM:SS. Defaults to the posting time.')
    einv_financial_year = fields.Char(
        string='Financial Year', compute='_compute_einv_financial_year',
        store=True, readonly=False)
    einv_reference_number = fields.Char(string='Reference Number')
    einv_buyer_reference = fields.Char(string='Buyer Reference')
    einv_buyer_accounting_reference = fields.Char(string='Accounting Cost')
    einv_transaction_type_code = fields.Selection(
        lk.TRANSACTION_TYPE_CODES, string='Transaction Type',
        compute='_compute_einv_defaults_from_company', store=True, readonly=False,
        help='Mandatory for AE sellers (rule BTUAE-002). Some types make '
             'further fields conditionally mandatory.',
    )
    einv_vat_taxpoint_date = fields.Date(
        string='VAT Tax Point Date',
        help='Must be before the issue date, otherwise the platform drops it '
             '(rule ibr-141).')
    einv_principle_id = fields.Char(string='Principle ID', help='Agent billing.')
    einv_beneficiary_id = fields.Char(string='Beneficiary ID')
    einv_vat_currency_id = fields.Many2one(
        'res.currency', string='VAT Accounting Currency',
        help='Cross-currency only. Must differ from the document currency, '
             'otherwise it is dropped (rule ibr-077).')
    einv_currency_exchange_rate = fields.Float(
        string='Currency Exchange Rate', digits=(16, 6),
        compute='_compute_einv_currency_exchange_rate', store=True, readonly=False,
        help='Required when invoicing in a currency other than AED.')
    einv_period_start = fields.Date(string='Invoicing Period Start')
    einv_period_end = fields.Date(string='Invoicing Period End')
    einv_billing_frequency = fields.Selection(
        lk.BILLING_FREQUENCY_CODES, string='Frequency of Billing')
    einv_note = fields.Char(
        string='Invoice Note', compute='_compute_einv_note', store=True, readonly=False,
        help='Free-text note sent as Note. Defaults from the invoice terms.')

    # References & documents
    einv_po_reference = fields.Char(
        string='Purchase Order Reference',
        compute='_compute_einv_po_reference', store=True, readonly=False)
    einv_so_reference = fields.Char(string='Sales Order Reference')
    einv_despatch_advice_ref = fields.Char(string='Despatch Advice Reference')
    einv_receiving_advice_ref = fields.Char(string='Receiving Advice Reference')
    einv_customs_ref = fields.Char(string='Customs Reference Number')
    einv_preceding_invoice_number = fields.Char(
        string='Preceding Invoice Number',
        compute='_compute_einv_preceding', store=True, readonly=False,
        help='The invoice being credited. Mandatory on 381 / 261.')
    einv_preceding_invoice_date = fields.Date(
        string='Preceding Invoice Date',
        compute='_compute_einv_preceding', store=True, readonly=False)
    einv_credit_note_reason_code = fields.Selection(
        lk.CREDIT_NOTE_REASON_CODES, string='Credit Note Reason',
        help='Mandatory on 381 / 261 (rule IBR-001-AE).')
    einv_lot_reference = fields.Char(string='Tender or Lot Reference')
    einv_project_reference = fields.Char(string='Project Reference')
    einv_contract_reference = fields.Char(string='Contract Reference')
    einv_contract_value = fields.Char(string='Contract Value / Description')
    einv_additional_doc_ref_id = fields.Char(string='Invoiced Object Identifier')
    einv_additional_doc_scheme_id = fields.Char(
        string='Invoiced Object Scheme',
        help='Must be a UNTDID 1153 code — 3 letters, e.g. AAK. A non-1153 '
             'value such as 0088 is dropped (rule ibr-cl-07).')
    einv_document_type_code = fields.Char(string='Supporting Document Type Code')
    einv_document_description = fields.Char(string='Supporting Document Description')
    einv_external_reference_id = fields.Char(
        string='External Document Location', help='URI of a supporting document.')

    # Delivery
    einv_actual_delivery_date = fields.Date(
        string='Actual Delivery Date',
        compute='_compute_einv_delivery_date', store=True, readonly=False)
    einv_deliver_to_location_id = fields.Char(string='Deliver To Location Identifier')
    einv_deliver_to_location_scheme = fields.Char(
        string='Deliver To Location Scheme',
        help='ICD scheme for the location identifier, e.g. 0088.')

    # Payment
    einv_payment_means_code = fields.Selection(
        lk.PAYMENT_MEANS_CODES, string='Payment Means',
        compute='_compute_einv_defaults_from_company', store=True, readonly=False,
        help='Mandatory on 380 / 389 (rule AE-PMC).')
    einv_payee_name = fields.Char(string='Payment Means Text')
    einv_payment_instructions = fields.Char(
        string='Remittance Information',
        compute='_compute_einv_payment_instructions', store=True, readonly=False)
    einv_payment_network_id = fields.Char(string='Network ID (BIC)')
    einv_card_holder_name = fields.Char(string='Payment Card Holder Name')
    einv_card_pan = fields.Char(
        string='Payment Card PAN',
        help='Last digits only — never store a full card number.')
    einv_payment_terms_text = fields.Char(
        string='Payment Terms Text',
        compute='_compute_einv_payment_terms_text', store=True, readonly=False)
    einv_payee_account_id = fields.Char(
        string='Payment Account (IBAN)',
        compute='_compute_einv_payee_account', store=True, readonly=False)
    einv_payee_account_name = fields.Char(
        string='Payment Account Name',
        compute='_compute_einv_payee_account', store=True, readonly=False)
    einv_payee_identifier = fields.Char(string='Payee Identifier')
    einv_payee_legal_reg_id = fields.Char(string='Payee Legal Registration Identifier')
    einv_prepaid_amount = fields.Monetary(
        string='Prepaid Amount', currency_field='currency_id',
        help='Amount already paid. The platform recomputes PayableAmount as '
             'TaxInclusive - Prepaid + Rounding (rule ibr-co-16).')
    einv_rounding_amount = fields.Monetary(
        string='Rounding Amount', currency_field='currency_id')

    einv_allowance_ids = fields.One2many(
        'einvoice.allowance', 'move_id', string='Allowances / Charges',
        help='Document-level discounts and charges. They adjust the taxable '
             'base per VAT category, so they also move the VAT.')

    einv_attach_pdf = fields.Boolean(
        string='Attach Invoice PDF',
        compute='_compute_einv_attach_pdf', store=True, readonly=False,
        help='Render the invoice report and send it in attachments[] as base64. '
             'Defaults to the company setting and can be overridden per document.',
    )
    einv_attach_documents = fields.Boolean(
        string='Attach Documents on this Invoice', default=True,
        help='Also send the files attached to this record — anything dropped in '
             'the chatter or added under Documents — encoded as base64.',
    )
    einv_attachment_count = fields.Integer(
        string='Files to Send', compute='_compute_einv_attachment_count',
        help='How many files the next push will carry in attachments[].')
    einv_attachment_ids = fields.Many2many(
        'ir.attachment', 'einvoice_move_attachment_rel', 'move_id', 'attachment_id',
        string='eInvoice Attachments',
        help='Files sent in attachments[] as base64. PDF, Word and Excel are '
             'the accepted mime types.')

    # ------------------------------------------------------------------
    # Seller block — the party issuing the document
    #
    # Auto-filled from the company and its address, then editable per
    # document. The platform overrides the seller from the token entity
    # profile on its side, so editing these changes what is transmitted but
    # not what the platform finally records — they are here because the
    # documented payload carries them and they have to be inspectable.
    # ------------------------------------------------------------------
    einv_seller_name = fields.Char(
        string='Seller Name', compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_trn = fields.Char(
        string='Seller Tax Identifier (TRN)',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_electronic_address = fields.Char(
        string='Seller Electronic Address',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_scheme_id = fields.Char(
        string='Seller Scheme Identifier',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_legal_reg_type = fields.Selection(
        lk.LEGAL_REG_TYPE_CODES, string='Seller Legal Registration Type',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_legal_reg_id = fields.Char(
        string='Seller Legal Registration Identifier',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_trade_license = fields.Char(
        string='Seller Commercial / Trade Licence',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_authority_name = fields.Char(
        string='Seller Issuing Authority',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_address1 = fields.Char(
        string='Seller Address Line 1',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_address2 = fields.Char(
        string='Seller Address Line 2',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_city = fields.Char(
        string='Seller City', compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_country_subdivision = fields.Char(
        string='Seller Emirate', compute='_compute_einv_seller', store=True, readonly=False,
        help='PINT-AE country subdivision code — AUH, DXB, SHJ, AJM, UAQ, RAK, FUJ.')
    einv_seller_postal_zone = fields.Char(
        string='Seller Post Code', compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_country_code = fields.Char(
        string='Seller Country Code', compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_contact_point = fields.Char(
        string='Seller Contact Point', compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_phone = fields.Char(
        string='Seller Contact Telephone',
        compute='_compute_einv_seller', store=True, readonly=False)
    einv_seller_email = fields.Char(
        string='Seller Contact Email', compute='_compute_einv_seller', store=True, readonly=False)

    # ------------------------------------------------------------------
    # Buyer block — the receiver of the transmission
    #
    # Auto-filled from the customer and editable per document, because a
    # one-off buyer detail (a passport on a walk-in sale, a different
    # accounts-payable contact) belongs on the invoice, not on the partner.
    # ------------------------------------------------------------------
    einv_buyer_name = fields.Char(
        string='Buyer Name', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_vat = fields.Char(
        string='Buyer VAT Identifier (TRN)',
        compute='_compute_einv_buyer', store=True, readonly=False,
        help='15 digits. Not the same thing as the Peppol electronic address.')
    einv_buyer_identifier = fields.Char(
        string='Buyer Identifier', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_electronic_address = fields.Char(
        string='Buyer Electronic Address',
        compute='_compute_einv_buyer', store=True, readonly=False,
        help='The buyer Peppol participant id — scheme + address form the UID '
             '(0235 + 1010101012 -> 0235:1010101012). When empty the platform '
             'falls back to the TRN.')
    einv_buyer_scheme_id = fields.Char(
        string='Buyer Scheme Identifier',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_email = fields.Char(
        string='Buyer Contact Email', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_contact_point = fields.Char(
        string='Buyer Contact Point', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_phone = fields.Char(
        string='Buyer Contact Telephone',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_address1 = fields.Char(
        string='Buyer Address Line 1', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_address2 = fields.Char(
        string='Buyer Address Line 2', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_city = fields.Char(
        string='Buyer City', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_country_subdivision = fields.Char(
        string='Buyer Emirate', compute='_compute_einv_buyer', store=True, readonly=False,
        help='PINT-AE country subdivision code — AUH, DXB, SHJ, AJM, UAQ, RAK, FUJ.')
    einv_buyer_postal_zone = fields.Char(
        string='Buyer Post Code', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_country_code = fields.Char(
        string='Buyer Country Code', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_legal_reg_type = fields.Selection(
        lk.LEGAL_REG_TYPE_CODES, string='Buyer Legal Registration Type',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_legal_reg_id = fields.Char(
        string='Buyer Legal Registration Identifier',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_trade_license = fields.Char(
        string='Buyer Commercial / Trade Licence',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_emirates_id = fields.Char(
        string='Buyer Emirates ID', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_passport = fields.Char(
        string='Buyer Passport', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_passport_country = fields.Char(
        string='Buyer Passport Issuing Country',
        compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_cabinet_decision = fields.Char(
        string='Buyer Cabinet Decision', compute='_compute_einv_buyer', store=True, readonly=False)
    einv_buyer_authority_name = fields.Char(
        string='Buyer Authority Name', compute='_compute_einv_buyer', store=True, readonly=False)

    # ------------------------------------------------------------------
    # Deliver-to block — auto-filled from the delivery address
    # ------------------------------------------------------------------
    einv_delivery_party_name = fields.Char(
        string='Deliver To Party Name',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_address1 = fields.Char(
        string='Deliver To Address Line 1',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_address2 = fields.Char(
        string='Deliver To Address Line 2',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_city = fields.Char(
        string='Deliver To City', compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_country_subdivision = fields.Char(
        string='Deliver To Emirate',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_postal_zone = fields.Char(
        string='Deliver To Post Code',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_delivery_country_code = fields.Char(
        string='Deliver To Country Code',
        compute='_compute_einv_delivery', store=True, readonly=False)
    einv_incoterms = fields.Char(
        string='Incoterms', compute='_compute_einv_delivery', store=True, readonly=False)

    # ------------------------------------------------------------------
    # Totals, mirrored so the whole transmitted map is visible in one place.
    # The platform derives these from the lines and allowances on submit, so
    # they are shown but never edited.
    # ------------------------------------------------------------------
    einv_tax_exclusive_amount = fields.Monetary(
        string='Total Without VAT', currency_field='currency_id',
        compute='_compute_einv_totals')
    einv_total_vat = fields.Monetary(
        string='Total VAT', currency_field='currency_id', compute='_compute_einv_totals')
    einv_tax_inclusive_amount = fields.Monetary(
        string='Total With VAT', currency_field='currency_id', compute='_compute_einv_totals')
    einv_payable_amount = fields.Monetary(
        string='Amount Due', currency_field='currency_id', compute='_compute_einv_totals',
        help='TaxInclusive - Prepaid + Rounding (rule ibr-co-16). Computed by '
             'the platform; shown here so the figure can be checked before pushing.')

    # AP inbound only
    einv_sender_id = fields.Char(string='Peppol Sender ID', readonly=True, copy=False)
    einv_receiver_id = fields.Char(string='Peppol Receiver ID', readonly=True, copy=False)
    einv_payload = fields.Text(
        string='Received Payload', readonly=True, copy=False,
        help='The full parsed PINT-AE field map as delivered by the platform.')

    # ==================================================================
    # Computes
    # ==================================================================
    @api.depends('move_type', 'company_id.einv_enabled', 'company_id.einv_ap_enabled')
    def _compute_einv_direction(self):
        for move in self:
            if move.move_type in AR_TYPES:
                move.einv_direction = 'ar'
                move.einv_applicable = bool(move.company_id.einv_enabled)
            elif move.move_type in AP_TYPES:
                move.einv_direction = 'ap'
                move.einv_applicable = bool(
                    move.company_id.einv_enabled or move.company_id.einv_ap_enabled)
            else:
                move.einv_direction = False
                move.einv_applicable = False

    @api.depends('move_type', 'einv_self_billed')
    def _compute_einv_invoice_type_code(self):
        """380 / 381 ordinarily, 389 / 261 when self-billed."""
        for move in self:
            if move.move_type in ('out_invoice', 'in_invoice'):
                move.einv_invoice_type_code = '389' if move.einv_self_billed else '380'
            elif move.move_type in ('out_refund', 'in_refund'):
                move.einv_invoice_type_code = '261' if move.einv_self_billed else '381'
            else:
                move.einv_invoice_type_code = False

    @api.depends('name', 'state')
    def _compute_einv_unique_invoice_number(self):
        """Derive a stable idempotency key from the posted document number.

        The key must never change between a first push and a retry, so it is
        only set once the sequence has been assigned and is left alone
        afterwards.
        """
        for move in self:
            if move.einv_unique_invoice_number:
                continue
            if move.move_type in AR_TYPES and move.name and move.name != '/':
                move.einv_unique_invoice_number = 'UIN-%s' % re.sub(
                    r'[^A-Za-z0-9._-]+', '-', move.name)
            else:
                move.einv_unique_invoice_number = False

    @api.depends('company_id.einv_default_push_state')
    def _compute_einv_push_state(self):
        for move in self:
            move.einv_push_state = move.company_id.einv_default_push_state or 'draft'

    @api.depends('company_id.einv_default_transaction_type',
                 'company_id.einv_default_payment_means', 'einv_invoice_type_code')
    def _compute_einv_defaults_from_company(self):
        for move in self:
            company = move.company_id
            move.einv_transaction_type_code = (
                move.einv_transaction_type_code
                or company.einv_default_transaction_type or '00000000')
            # A credit note does not need payment means, but sending it is harmless.
            move.einv_payment_means_code = (
                move.einv_payment_means_code or company.einv_default_payment_means or '30')

    @api.depends('invoice_date')
    def _compute_einv_financial_year(self):
        for move in self:
            move.einv_financial_year = (
                str(move.invoice_date.year) if move.invoice_date else False)

    @api.depends('currency_id', 'company_currency_id', 'invoice_date')
    def _compute_einv_currency_exchange_rate(self):
        """Rate from the document currency to the company currency."""
        for move in self:
            if move.currency_id and move.company_currency_id \
                    and move.currency_id != move.company_currency_id:
                rate = move.currency_id._convert(
                    1.0, move.company_currency_id, move.company_id,
                    move.invoice_date or fields.Date.context_today(move))
                move.einv_currency_exchange_rate = float_round(rate, precision_digits=6)
            else:
                move.einv_currency_exchange_rate = 0.0

    @api.depends('narration')
    def _compute_einv_note(self):
        for move in self:
            if move.einv_note:
                continue
            text = re.sub(r'<[^>]+>', ' ', move.narration or '')
            text = re.sub(r'\s+', ' ', text).strip()
            move.einv_note = text[:300] or False

    @api.depends('invoice_origin', 'ref')
    def _compute_einv_po_reference(self):
        for move in self:
            if move.einv_po_reference:
                continue
            move.einv_po_reference = move.invoice_origin or move.ref or False

    @api.depends('reversed_entry_id')
    def _compute_einv_preceding(self):
        """A credit note created by reversal already knows its origin."""
        for move in self:
            origin = move.reversed_entry_id
            if origin and not move.einv_preceding_invoice_number:
                move.einv_preceding_invoice_number = origin.name
                move.einv_preceding_invoice_date = origin.invoice_date

    @api.depends('invoice_date')
    def _compute_einv_delivery_date(self):
        for move in self:
            if not move.einv_actual_delivery_date:
                move.einv_actual_delivery_date = move.invoice_date

    @api.depends('payment_reference', 'name')
    def _compute_einv_payment_instructions(self):
        for move in self:
            if move.einv_payment_instructions:
                continue
            move.einv_payment_instructions = move.payment_reference or move.name or False

    @api.depends('invoice_payment_term_id')
    def _compute_einv_payment_terms_text(self):
        for move in self:
            if move.einv_payment_terms_text:
                continue
            move.einv_payment_terms_text = move.invoice_payment_term_id.name or False

    @api.depends('partner_bank_id')
    def _compute_einv_payee_account(self):
        for move in self:
            bank = move.partner_bank_id
            if not move.einv_payee_account_id:
                move.einv_payee_account_id = bank.acc_number or False
            if not move.einv_payee_account_name:
                move.einv_payee_account_name = bank.acc_holder_name or bank.partner_id.name or False

    @api.depends('company_id', 'company_id.partner_id', 'company_id.vat',
                 'company_id.einv_seller_scheme_id',
                 'company_id.einv_seller_electronic_address',
                 'company_id.einv_legal_reg_type', 'company_id.einv_legal_reg_id',
                 'company_id.einv_trade_license', 'company_id.einv_authority_name',
                 'company_id.einv_contact_point')
    def _compute_einv_seller(self):
        """Fill the seller block from the company, leaving it editable.

        Everything is overwritten when the company changes, which is what a
        user expects: the seller identity belongs to the issuing entity, not to
        the individual invoice.
        """
        for move in self:
            company = move.company_id
            partner = company.partner_id
            trn = (company.vat or '').replace(' ', '')
            move.einv_seller_name = company.name or False
            move.einv_seller_trn = trn or False
            move.einv_seller_electronic_address = (
                company.einv_seller_electronic_address or trn or False)
            move.einv_seller_scheme_id = company.einv_seller_scheme_id or '0235'
            move.einv_seller_legal_reg_type = company.einv_legal_reg_type or False
            move.einv_seller_legal_reg_id = company.einv_legal_reg_id or False
            move.einv_seller_trade_license = company.einv_trade_license or False
            move.einv_seller_authority_name = company.einv_authority_name or False
            move.einv_seller_address1 = partner.street or False
            move.einv_seller_address2 = partner.street2 or False
            move.einv_seller_city = partner.city or False
            move.einv_seller_country_subdivision = partner.einv_emirate_code or False
            move.einv_seller_postal_zone = partner.zip or False
            move.einv_seller_country_code = partner.country_id.code or 'AE'
            move.einv_seller_contact_point = company.einv_contact_point or False
            move.einv_seller_phone = company.phone or False
            move.einv_seller_email = company.email or False

    @api.depends('partner_id', 'partner_id.vat', 'partner_id.einv_peppol_id',
                 'partner_id.einv_peppol_scheme', 'partner_id.street', 'partner_id.city')
    def _compute_einv_buyer(self):
        """Fill the buyer block from the customer, leaving it editable.

        The identity comes from the commercial (parent) partner because that is
        the legal entity being invoiced, while the contact details and the
        address come from the invoicing contact when it carries one.
        """
        for move in self:
            partner = move.partner_id
            commercial = partner.commercial_partner_id
            address = partner if partner.street else commercial
            trn = (commercial.vat or partner.vat or '').replace(' ', '')
            move.einv_buyer_name = commercial.name or partner.name or False
            move.einv_buyer_vat = trn or False
            move.einv_buyer_identifier = (
                commercial.einv_buyer_identifier or partner.ref or False)
            move.einv_buyer_electronic_address = commercial.einv_peppol_id or trn or False
            move.einv_buyer_scheme_id = commercial.einv_peppol_scheme or '0235'
            move.einv_buyer_email = partner.email or commercial.email or False
            move.einv_buyer_contact_point = (
                partner.name if partner != commercial else False)
            move.einv_buyer_phone = (
                partner.phone or partner.mobile or commercial.phone or False)
            move.einv_buyer_address1 = address.street or False
            move.einv_buyer_address2 = address.street2 or False
            move.einv_buyer_city = address.city or False
            move.einv_buyer_country_subdivision = address.einv_emirate_code or False
            move.einv_buyer_postal_zone = address.zip or False
            move.einv_buyer_country_code = address.country_id.code or 'AE'
            move.einv_buyer_legal_reg_type = commercial.einv_legal_reg_type or False
            move.einv_buyer_legal_reg_id = commercial.einv_legal_reg_id or False
            move.einv_buyer_trade_license = commercial.einv_trade_license or False
            move.einv_buyer_emirates_id = commercial.einv_emirates_id or False
            move.einv_buyer_passport = commercial.einv_passport or False
            move.einv_buyer_passport_country = (
                commercial.einv_passport_country_id.code or False)
            move.einv_buyer_cabinet_decision = commercial.einv_cabinet_decision or False
            move.einv_buyer_authority_name = commercial.einv_authority_name or False

    @api.depends('partner_shipping_id', 'invoice_incoterm_id')
    def _compute_einv_delivery(self):
        """Fill the deliver-to block from the delivery address.

        Only filled when the goods go somewhere other than the invoicing
        address — an identical deliver-to party adds nothing to the document.
        """
        for move in self:
            shipping = move.partner_shipping_id
            distinct = shipping and shipping != move.partner_id
            move.einv_delivery_party_name = shipping.name if distinct else False
            move.einv_delivery_address1 = shipping.street if distinct else False
            move.einv_delivery_address2 = shipping.street2 if distinct else False
            move.einv_delivery_city = shipping.city if distinct else False
            move.einv_delivery_country_subdivision = (
                shipping.einv_emirate_code if distinct else False)
            move.einv_delivery_postal_zone = shipping.zip if distinct else False
            move.einv_delivery_country_code = (
                shipping.country_id.code if distinct else False)
            move.einv_incoterms = move.invoice_incoterm_id.code or False

    @api.depends('amount_untaxed', 'amount_tax', 'amount_total',
                 'einv_prepaid_amount', 'einv_rounding_amount')
    def _compute_einv_totals(self):
        """Mirror the totals the way the platform reports them.

        Absolute values: a credit note carries positive amounts, exactly like
        the invoice it reverses.
        """
        for move in self:
            move.einv_tax_exclusive_amount = abs(move.amount_untaxed)
            move.einv_total_vat = abs(move.amount_tax)
            move.einv_tax_inclusive_amount = abs(move.amount_total)
            move.einv_payable_amount = (
                abs(move.amount_total)
                - (move.einv_prepaid_amount or 0.0)
                + (move.einv_rounding_amount or 0.0))

    @api.depends('company_id.einv_attach_pdf')
    def _compute_einv_attach_pdf(self):
        for move in self:
            move.einv_attach_pdf = move.company_id.einv_attach_pdf

    @api.depends('einv_attachment_ids', 'einv_attach_pdf', 'einv_attach_documents')
    def _compute_einv_attachment_count(self):
        for move in self:
            move.einv_attachment_count = len(move._einv_files_to_send()) + (
                1 if move.einv_attach_pdf else 0)

    @api.depends('einv_error_ids')
    def _compute_einv_error_count(self):
        for move in self:
            move.einv_error_count = len(move.einv_error_ids)

    @api.depends('einv_log_ids')
    def _compute_einv_log_count(self):
        for move in self:
            move.einv_log_count = len(move.einv_log_ids)

    @api.depends('einv_state')
    def _compute_einv_locked(self):
        for move in self:
            move.einv_locked = move.einv_state in ('submitted', 'cleared')

    # ==================================================================
    # Payload construction
    # ==================================================================
    def _einv_seller_payload(self):
        """Seller block, read from the document.

        The fields are auto-filled from the company but live on the invoice, so
        what is transmitted is exactly what the form shows. The platform
        overrides the seller from the token entity on its side — to change the
        seller for good, edit the organisation profile, not the invoice.
        """
        self.ensure_one()
        vals = {
            'SellerName': self.einv_seller_name or '',
            'SellerTaxidentifier': self.einv_seller_trn or '',
            'SellerElectronicAddress': self.einv_seller_electronic_address or '',
            'SellerSchemeidentifier': self.einv_seller_scheme_id or '',
            'SellerLegalRegistrationType': self.einv_seller_legal_reg_type or '',
            'SellerLegalRegistrationIdentifier': self.einv_seller_legal_reg_id or '',
            'SellerCommercialTradelicense': self.einv_seller_trade_license or '',
            'SellerAuthorityname': self.einv_seller_authority_name or '',
            'SellerAddressLine1': self.einv_seller_address1 or '',
            'SellerAddressLine2': self.einv_seller_address2 or '',
            'SellerCity': self.einv_seller_city or '',
            'SellerCountrySubdivision': self.einv_seller_country_subdivision or '',
            'SellerPostalZone': self.einv_seller_postal_zone or '',
            'SellerCountryCode': self.einv_seller_country_code or '',
            'SellerContactPoint': self.einv_seller_contact_point or '',
            'SellerContactTelephone': self.einv_seller_phone or '',
            'SellerEmail': self.einv_seller_email or '',
        }
        return {k: v for k, v in vals.items() if v}

    def _einv_buyer_payload(self):
        """Buyer block, read from the document — the receiver of the transmission."""
        self.ensure_one()
        vals = {
            'BuyerName': self.einv_buyer_name or '',
            'BuyerVatIdentifier': self.einv_buyer_vat or '',
            'BuyerIdentifier': self.einv_buyer_identifier or '',
            'BuyerElectronicAddress': self.einv_buyer_electronic_address or '',
            'BuyerSchemeidentifier': self.einv_buyer_scheme_id or '',
            'BuyerEmail': self.einv_buyer_email or '',
            'BuyerContactPoint': self.einv_buyer_contact_point or '',
            'BuyerContactTelephone': self.einv_buyer_phone or '',
            'BuyerAddressLine1': self.einv_buyer_address1 or '',
            'BuyerAddressLine2': self.einv_buyer_address2 or '',
            'BuyerCity': self.einv_buyer_city or '',
            'BuyerCountrySubdivision': self.einv_buyer_country_subdivision or '',
            'BuyerPostalZone': self.einv_buyer_postal_zone or '',
            'BuyerCountryCode': self.einv_buyer_country_code or 'AE',
            'Buyerlegalregistrationidentifiertype': self.einv_buyer_legal_reg_type or '',
            'BuyerLegalRegistrationIdentifier': self.einv_buyer_legal_reg_id or '',
            'BuyerCommercialorTradelicense': self.einv_buyer_trade_license or '',
            'BuyerEmiratesID': self.einv_buyer_emirates_id or '',
            'BuyerPassport': self.einv_buyer_passport or '',
            'BuyerPassportIssuingCountrycode': self.einv_buyer_passport_country or '',
            'BuyerCabinetDecision': self.einv_buyer_cabinet_decision or '',
            'BuyerAuthorityName': self.einv_buyer_authority_name or '',
        }
        return {k: v for k, v in vals.items() if v}

    def _einv_delivery_payload(self):
        """Delivery block, read from the document."""
        self.ensure_one()
        vals = {
            'DeliverToPartyName': self.einv_delivery_party_name or '',
            'DeliverToLocationIdentifier': self.einv_deliver_to_location_id or '',
            'DeliverToAddressLine1': self.einv_delivery_address1 or '',
            'DeliverToAddressLine2': self.einv_delivery_address2 or '',
            'DeliverToCity': self.einv_delivery_city or '',
            'DeliverToCountrySubdivision': self.einv_delivery_country_subdivision or '',
            'DeliverToPostalZone': self.einv_delivery_postal_zone or '',
            'DeliverToCountryCode': self.einv_delivery_country_code or '',
            'Incoterms': self.einv_incoterms or '',
        }
        if self.einv_actual_delivery_date:
            vals['ActualDeliveryDate'] = self.einv_actual_delivery_date.isoformat()
        # The scheme only means anything alongside the identifier it qualifies.
        if self.einv_deliver_to_location_id and self.einv_deliver_to_location_scheme:
            vals['DeliverToLocationSchemeID'] = self.einv_deliver_to_location_scheme
        return {k: v for k, v in vals.items() if v}

    def _einv_payment_payload(self):
        """Payment block, read from the document."""
        self.ensure_one()
        vals = {
            'PaymentMeansCode': self.einv_payment_means_code or '',
            'PayeeName': self.einv_payee_name or '',
            'PaymentInstructions': self.einv_payment_instructions or '',
            'PaymentNetworkId': self.einv_payment_network_id or '',
            'PaymentCardHolderName': self.einv_card_holder_name or '',
            'PaymentCardPAN': self.einv_card_pan or '',
            'PaymentTerms': self.einv_payment_terms_text or '',
            'PayeeAccountID': self.einv_payee_account_id or '',
            'PayeeAccountName': self.einv_payee_account_name or '',
            'PayeeIdentifier': self.einv_payee_identifier or '',
            'PayeeLegalRegistrationIdentifier': self.einv_payee_legal_reg_id or '',
        }
        return {k: v for k, v in vals.items() if v}

    def _einv_invoice_lines(self):
        """The lines that become ``items[]``.

        Section and note lines carry no amounts and have no PINT-AE equivalent,
        so they are dropped.
        """
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note'))

    # Base64 of a file is about a third larger than the file itself, and the
    # whole payload travels in one JSON body, so an oversized attachment is
    # skipped rather than allowed to time the push out.
    EINV_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

    def _einv_files_to_send(self):
        """The attachments this document will carry, deduplicated.

        Explicitly chosen files first, then — when the flag is on — everything
        else attached to the record, so a PDF dropped in the chatter goes with
        the invoice without anyone having to re-pick it. The generated invoice
        PDF is not included here; it is rendered at push time.
        """
        self.ensure_one()
        files = self.einv_attachment_ids
        if self.einv_attach_documents and self.id:
            attached = self.env['ir.attachment'].search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', self.id),
            ])
            # A stored copy of our own generated PDF would otherwise be sent
            # twice once the report has been printed at least once.
            attached = attached.filtered(
                lambda a: a.mimetype in lk.ATTACHMENT_MIME_CODES
                and a.res_field is False)
            files |= attached
        return files

    def _einv_encode_attachment(self, name, raw, mime):
        """One attachments[] entry: file name, mime code and the base64 body.

        The platform wants a bare base64 string with no ``data:`` prefix.
        """
        self.ensure_one()
        if len(raw) > self.EINV_MAX_ATTACHMENT_BYTES:
            _logger.warning(
                'eInvoice: skipping attachment %s on %s — %.1f MB exceeds the '
                '%.0f MB limit.', name, self.name, len(raw) / 1048576.0,
                self.EINV_MAX_ATTACHMENT_BYTES / 1048576.0)
            return None
        return {
            'fileName': name,
            'mimeCode': mime,
            'base64': base64.b64encode(raw).decode(),
        }

    def _einv_invoice_pdf(self):
        """Render the invoice report, for attachments[].

        A report failure must never stop the push — the attachment is never the
        point of the transmission.
        """
        self.ensure_one()
        try:
            report = self.env['ir.actions.report']._render_qweb_pdf(
                'account.account_invoices', self.ids)
        except Exception as exc:
            _logger.warning(
                'eInvoice: could not render the PDF for %s: %s', self.name, exc)
            return None
        content = report[0] if isinstance(report, tuple) else report
        if not content:
            return None
        return self._einv_encode_attachment(
            '%s.pdf' % re.sub(r'[^A-Za-z0-9._-]+', '-', self.name or 'invoice'),
            content, 'application/pdf')

    def _einv_attachments_payload(self):
        """attachments[]: the invoice PDF plus every supporting document.

        Everything is base64-encoded here. A file whose type the platform does
        not accept, or which is too big, is skipped and logged rather than
        failing the push.
        """
        self.ensure_one()
        payload = []
        if self.einv_attach_pdf:
            entry = self._einv_invoice_pdf()
            if entry:
                payload.append(entry)
        for attachment in self._einv_files_to_send():
            mime = attachment.mimetype or 'application/octet-stream'
            if mime not in lk.ATTACHMENT_MIME_CODES:
                _logger.info(
                    'eInvoice: skipping attachment %s on %s — the platform does '
                    'not accept %s.', attachment.name, self.name, mime)
                continue
            raw = attachment.raw
            if not raw:
                continue
            entry = self._einv_encode_attachment(attachment.name, raw, mime)
            if entry:
                payload.append(entry)
        return payload

    def _einv_payload(self):
        """The complete field map for this invoice.

        Totals are included so the payload mirrors the portal view, but the
        platform derives them from the lines and allowances on submit — so
        whatever is sent for them is recomputed.
        """
        self.ensure_one()
        company = self.company_id
        type_code = self.einv_invoice_type_code or '380'

        data = {
            # Control — not part of the XML.
            'UniqueInvoiceNumber': self.einv_unique_invoice_number or '',
            'PushState': self.einv_push_state or company.einv_default_push_state or 'draft',
            # Invoice details.
            'InvoiceID': self.name or '',
            'IssueDate': (self.invoice_date or fields.Date.context_today(self)).isoformat(),
            'InvoiceTypeCode': type_code,
            'DocumentCurrencyCode': self.currency_id.name or 'AED',
            'InvoiceTransactionTypeCode': self.einv_transaction_type_code or '00000000',
        }
        if self.einv_issue_time:
            data['IssueTime'] = self.einv_issue_time
        elif self.create_date:
            data['IssueTime'] = fields.Datetime.context_timestamp(
                self, self.create_date).strftime('%H:%M:%S')
        if self.invoice_date_due:
            data['DueDate'] = self.invoice_date_due.isoformat()

        optional_header = {
            'FinancialYear': self.einv_financial_year,
            'ReferenceNumber': self.einv_reference_number,
            'BuyerReference': self.einv_buyer_reference,
            'BuyerAccountingReference': self.einv_buyer_accounting_reference,
            'PrincipleID': self.einv_principle_id,
            'BeneficiaryID': self.einv_beneficiary_id,
            'FrequencyofBilling': self.einv_billing_frequency,
            'Note': self.einv_note,
            'Purchaseorderreference': self.einv_po_reference,
            'Salesorderreference': self.einv_so_reference,
            'Despatchadvicereference': self.einv_despatch_advice_ref,
            'Receivingadvicereference': self.einv_receiving_advice_ref,
            'Customsreferencenumber': self.einv_customs_ref,
            'LotReference': self.einv_lot_reference,
            'ProjectReference': self.einv_project_reference,
            'ContractReference': self.einv_contract_reference,
            'ContractValue': self.einv_contract_value,
            'AdditionalDocumentReferenceID': self.einv_additional_doc_ref_id,
            'AdditionalDocSchemeID': self.einv_additional_doc_scheme_id,
            'DocumentTypecode': self.einv_document_type_code,
            'DocumentDescription': self.einv_document_description,
            'ExternalReferenceID': self.einv_external_reference_id,
        }
        data.update({k: v for k, v in optional_header.items() if v})

        for fname, key in (('einv_period_start', 'InvoicePeriodStartDate'),
                           ('einv_period_end', 'InvoicePeriodEndDate'),
                           ('einv_vat_taxpoint_date', 'VATtaxpointdate'),
                           ('einv_preceding_invoice_date', 'PrecedingInvoiceIssueDate')):
            value = self[fname]
            if value:
                data[key] = value.isoformat()

        # Cross-currency. A VAT currency equal to the document currency is
        # dropped by the platform (rule ibr-077), so it is only sent when it
        # genuinely differs.
        if self.einv_vat_currency_id and self.einv_vat_currency_id != self.currency_id:
            data['VATCurrencyCode'] = self.einv_vat_currency_id.name
        if self.einv_currency_exchange_rate:
            data['CurrencyExchangeRate'] = str(self.einv_currency_exchange_rate)

        # Credit-note specifics — mandatory on 381 / 261.
        if type_code in lk.CREDIT_NOTE_TYPE_CODES:
            if self.einv_preceding_invoice_number:
                data['PrecedingInvoiceNumber'] = self.einv_preceding_invoice_number
            if self.einv_credit_note_reason_code:
                data['Creditnotereasoncode'] = self.einv_credit_note_reason_code
        elif self.einv_preceding_invoice_number:
            data['PrecedingInvoiceNumber'] = self.einv_preceding_invoice_number

        data.update(self._einv_seller_payload())
        data.update(self._einv_buyer_payload())
        data.update(self._einv_delivery_payload())
        data.update(self._einv_payment_payload())

        lines = self._einv_invoice_lines()
        data['items'] = [
            line._einv_item_payload(index)
            for index, line in enumerate(lines, start=1)
        ]
        if self.einv_allowance_ids:
            data['allowances'] = [a._einv_payload() for a in self.einv_allowance_ids]

        # Totals are absolute: a credit note carries positive amounts, exactly
        # like the invoice it reverses.
        data.update({
            'TaxExclusiveAmount': round(abs(self.amount_untaxed), 2),
            'totalVat': round(abs(self.amount_tax), 2),
            'TaxInclusiveAmount': round(abs(self.amount_total), 2),
        })
        if self.einv_prepaid_amount:
            data['PrepaidAmount'] = round(self.einv_prepaid_amount, 2)
        if self.einv_rounding_amount:
            data['PayableRoundingAmount'] = round(self.einv_rounding_amount, 2)

        attachments = self._einv_attachments_payload()
        if attachments:
            data['attachments'] = attachments
        return data

    # ==================================================================
    # Local pre-validation
    # ==================================================================
    def _einv_check(self):
        """Catch the mandatory fields locally, before spending an API call.

        These are the rules the guide lists as easy to miss; the platform runs
        the full PINT-AE set and its errors are authoritative.
        """
        self.ensure_one()
        problems = []
        type_code = self.einv_invoice_type_code

        if not self.einv_unique_invoice_number:
            problems.append(_('Unique Invoice Number is required (idempotency key).'))
        if not self.name or self.name == '/':
            problems.append(_('The invoice has no document number — post it first.'))
        if not self.invoice_date:
            problems.append(_('Invoice date is required.'))
        if not type_code:
            problems.append(_('Invoice type code is required.'))
        if not self.einv_buyer_name:
            problems.append(_('Buyer name is required.'))
        if not self.einv_transaction_type_code:
            problems.append(_('Transaction type code is required for AE sellers (BTUAE-002).'))
        if type_code in lk.PAYMENT_MEANS_REQUIRED_CODES and not self.einv_payment_means_code:
            problems.append(_('Payment means code is required on a %s document (AE-PMC).',
                              type_code))
        if type_code in lk.CREDIT_NOTE_TYPE_CODES:
            if not self.einv_preceding_invoice_number:
                problems.append(_('Preceding invoice number is required for a credit note.'))
            if not self.einv_credit_note_reason_code:
                problems.append(_('Credit note reason code is required for a credit note '
                                  '(IBR-001-AE).'))

        lines = self._einv_invoice_lines()
        if not lines:
            problems.append(_('An invoice must have at least one line (BR-16).'))
        for index, line in enumerate(lines, start=1):
            label = line._einv_label() or _('line %s', index)
            if not (line.name or line.product_id):
                problems.append(_('Line %s has no description.', index))
            if line.einv_item_type in ('S', 'B') and not line.einv_sac_code:
                problems.append(_(
                    '"%s" is a service line and needs a Service Accounting Code '
                    '(VAL-ITEM-SAC). Fill the SAC column on the line, or set it '
                    'on the product so it fills in by itself.', label))
            if line.einv_item_type in ('G', 'B') and not line.einv_hs_code:
                problems.append(_(
                    '"%s" is a goods line and needs an HS classification '
                    '(VAL-ITEM-CLASS). Fill the HS Code column on the line, or '
                    'set it on the product so it fills in by itself.', label))
        return problems

    def action_einv_check(self):
        """Show the local pre-validation result without calling the platform."""
        self.ensure_one()
        problems = self._einv_check()
        if problems:
            raise UserError(_('This invoice is not ready to be pushed:\n\n%s')
                            % '\n'.join('• %s' % p for p in problems))
        return self._einv_notify(
            _('Ready to push'),
            _('No local validation problem found. The platform runs the full '
              'PINT-AE rule set on push.'), 'success')

    def action_einv_preview_payload(self):
        """Open the JSON that would be sent, for support and debugging."""
        self.ensure_one()
        payload = self._einv_payload()
        # The base64 body of an attachment is noise in a preview.
        for attachment in payload.get('attachments', []):
            attachment['base64'] = '<%d bytes>' % len(attachment.get('base64') or '')
        log = self.env['einvoice.log']._log({
            'company_id': self.company_id.id,
            'move_id': self.id,
            'direction': 'ar',
            'operation': 'push',
            'endpoint': _('preview — not sent'),
            'success': True,
            'unique_invoice_number': self.einv_unique_invoice_number,
            'message': _('Payload preview generated by %s', self.env.user.display_name),
            'request_body': {'data': payload},
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payload Preview'),
            'res_model': 'einvoice.log',
            'res_id': log.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ==================================================================
    # Push
    # ==================================================================
    def _einv_pushable(self):
        """The subset of ``self`` that may be pushed right now."""
        return self.filtered(
            lambda m: m.move_type in AR_TYPES
            and m.state == 'posted'
            and m.company_id.einv_enabled
            and not m.einv_locked
        )

    def action_einv_push(self):
        """Push the selected AR documents, batching at the platform limit."""
        moves = self._einv_pushable()
        if not moves:
            raise UserError(_(
                'Nothing to push. An invoice must be a posted customer invoice '
                'or credit note of a company with eInvoicing enabled, and must '
                'not already be submitted.'))
        summary = moves._einv_push()
        return self._einv_notify(
            _('eInvoicing'),
            _('%(ok)s succeeded, %(ko)s failed, %(sub)s submitted.',
              ok=summary['succeeded'], ko=summary['failed'], sub=summary['submitted']),
            'success' if not summary['failed'] else 'warning')

    def action_einv_submit(self):
        """Push with PushState "submit" regardless of the configured default."""
        self.filtered(lambda m: not m.einv_locked).einv_push_state = 'submit'
        return self.action_einv_push()

    def _einv_push(self, push_state=None):
        """Send these invoices and apply the response to each record.

        Grouped by company because the token, the base URL and the entity all
        come from the company; batched at 200, the documented maximum.
        """
        totals = {'succeeded': 0, 'failed': 0, 'submitted': 0}
        for company, moves in self.grouped('company_id').items():
            token = company.sudo().einv_api_token
            if not token:
                raise UserError(_(
                    'No outbound API token is configured for %s. Set it in '
                    'Settings > Accounting > KGRN eInvoicing, or issue one with '
                    'the Generate Token wizard.', company.display_name))
            ordered = moves.sorted('id')
            for start in range(0, len(ordered), lk.MAX_BATCH_SIZE):
                batch = ordered[start:start + lk.MAX_BATCH_SIZE]
                result = batch._einv_push_batch(company, token, push_state=push_state)
                for key in totals:
                    totals[key] += result.get(key, 0)
        return totals

    def _einv_push_batch(self, company, token, push_state=None):
        """One HTTP call for up to 200 invoices, plus the response handling."""
        payloads = []
        for move in self:
            data = move._einv_payload()
            if push_state:
                data['PushState'] = push_state
            payloads.append(data)

        body = ({'data': payloads[0]} if len(payloads) == 1
                else {'invoices': payloads})
        url = company._einv_api_url('external/outbound/invoice')

        status, response, error = self.env['einvoice.api']._request(
            'POST', url, token=token, payload=body,
            timeout=company.einv_timeout or 60)

        log_vals = {
            'company_id': company.id,
            'direction': 'ar',
            'operation': 'push',
            'endpoint': url,
            'http_status': status,
            'request_body': body,
            'response_body': response if response is not None else error,
        }
        if len(self) == 1:
            log_vals['move_id'] = self.id
            log_vals['unique_invoice_number'] = self.einv_unique_invoice_number

        # Transport failure — nothing was decided about any invoice. Retrying
        # with the same UniqueInvoiceNumber is safe, so the records are left
        # exactly as they were apart from the error message.
        if error is not None:
            log_vals.update({'success': False, 'message': error})
            self.env['einvoice.log']._log(log_vals)
            self.write({
                'einv_state': 'error',
                'einv_error_code': 'TRANSPORT_ERROR',
                'einv_message': error,
                'einv_last_push_date': fields.Datetime.now(),
            })
            return {'succeeded': 0, 'failed': len(self), 'submitted': 0}

        request_id = (response or {}).get('requestId')
        log_vals['request_id'] = request_id

        # 401 / 403 carry {"error": "..."} with no errorCode; 400 carries
        # errorCode/message. Neither returns results[].
        if status in (400, 401, 403, 500, 502) or 'results' not in (response or {}):
            message = (response or {}).get('error') or (response or {}).get('message') \
                or _('HTTP %s from the eInvoicing platform.', status)
            error_code = (response or {}).get('errorCode') or 'HTTP_%s' % status
            log_vals.update({'success': False, 'message': message, 'error_code': error_code})
            self.env['einvoice.log']._log(log_vals)
            self.write({
                'einv_state': 'error',
                'einv_error_code': error_code,
                'einv_message': message,
                'einv_request_id': request_id,
                'einv_last_push_date': fields.Datetime.now(),
            })
            return {'succeeded': 0, 'failed': len(self), 'submitted': 0}

        # Refresh what the token resolved to; it is free information.
        entity = response.get('entity') or {}
        location = response.get('location') or {}
        company.sudo().write({
            'einv_entity_name': entity.get('name') or company.einv_entity_name,
            'einv_entity_trn': entity.get('trn') or company.einv_entity_trn,
            'einv_location_name': location.get('name') or company.einv_location_name,
        })

        summary = response.get('summary') or {}
        log_vals.update({
            'success': bool(response.get('success')),
            'message': _('%(t)s total, %(s)s succeeded, %(f)s failed, %(sub)s submitted',
                         t=summary.get('total', 0), s=summary.get('succeeded', 0),
                         f=summary.get('failed', 0), sub=summary.get('submitted', 0)),
        })
        self.env['einvoice.log']._log(log_vals)

        # results[] comes back in the order supplied, but it is matched on the
        # idempotency key rather than on position so a reordered or short
        # response can never write an outcome onto the wrong invoice.
        by_key = {m.einv_unique_invoice_number: m for m in self}
        counters = {'succeeded': 0, 'failed': 0, 'submitted': 0}
        for index, result in enumerate(response.get('results') or []):
            move = by_key.get(result.get('uniqueInvoiceNumber'))
            if not move and index < len(self):
                move = self[index]
            if not move:
                continue
            move._einv_apply_result(result, request_id=request_id, company=company)
            if result.get('success'):
                counters['succeeded'] += 1
            else:
                counters['failed'] += 1
            if result.get('submitted'):
                counters['submitted'] += 1
        return counters

    def _einv_apply_result(self, result, request_id=None, company=None):
        """Write one ``results[]`` entry back onto the invoice.

        An invoice is FTA-cleared only when the result reports success AND the
        Peppol block reports SUCCESS — success alone just means the draft was
        stored.
        """
        self.ensure_one()
        peppol = result.get('peppol') or {}
        error_code = result.get('errorCode')
        vals = {
            'einv_record_id': result.get('recordId') or self.einv_record_id,
            'einv_request_id': request_id or self.einv_request_id,
            'einv_peppol_status': peppol.get('status') or False,
            'einv_message': result.get('message') or False,
            'einv_error_code': error_code or False,
            'einv_platform_status': result.get('status') or False,
            'einv_last_push_date': fields.Datetime.now(),
        }
        if peppol.get('instanceIdentifier'):
            vals['einv_instance_id'] = peppol['instanceIdentifier']
        if peppol.get('senderParticipantId'):
            vals['einv_sender_id'] = peppol['senderParticipantId']
        if peppol.get('receiverParticipantId'):
            vals['einv_receiver_id'] = peppol['receiverParticipantId']

        # Stale validation errors would otherwise linger after a fix.
        self.einv_error_ids.unlink()

        if result.get('success'):
            if peppol.get('status') == 'SUCCESS':
                vals['einv_state'] = 'cleared'
            else:
                vals['einv_state'] = {
                    'cleared': 'cleared', 'submitted': 'submitted',
                    'rejected': 'rejected', 'draft': 'draft',
                }.get(result.get('status'), 'draft')
        elif error_code == 'ALREADY_SUBMITTED':
            # Protective, not a failure: the cleared invoice is untouched.
            vals['einv_state'] = 'submitted'
        elif error_code == 'VALIDATION_FAILED':
            # The platform stores it as a correctable draft, but for the
            # operator this is an error: the fields have to be fixed and the
            # same key resent. The platform's own status stays in
            # einv_platform_status.
            vals['einv_state'] = 'error'
            self.env['einvoice.error'].sudo().create([{
                'move_id': self.id,
                'rule': err.get('rule'),
                'field_name': err.get('field'),
                'message': err.get('message'),
                'fix': err.get('fix'),
            } for err in result.get('errors') or []])
        elif error_code == 'PEPPOL_REJECTED':
            vals['einv_state'] = 'rejected'
        else:
            vals['einv_state'] = 'error'

        self.write(vals)
        self._einv_post_result_message(result)

        self.env['einvoice.log']._log({
            'company_id': (company or self.company_id).id,
            'move_id': self.id,
            'direction': 'ar',
            'operation': 'push',
            'success': bool(result.get('success')),
            'http_status': 0,
            'request_id': request_id,
            'unique_invoice_number': result.get('uniqueInvoiceNumber'),
            'record_id': result.get('recordId'),
            'instance_id': peppol.get('instanceIdentifier'),
            'error_code': error_code,
            'message': result.get('message'),
            'response_body': result,
        })
        return True

    def _einv_post_result_message(self, result):
        """Log the outcome in the chatter, so it lives with the document."""
        self.ensure_one()
        if result.get('success'):
            body = _('eInvoicing: %(action)s — status %(status)s.',
                     action=result.get('action') or 'pushed',
                     status=self.einv_state)
            if self.einv_instance_id:
                body += _(' Peppol instance %s.', self.einv_instance_id)
        else:
            body = _('eInvoicing failed: %(code)s — %(msg)s',
                     code=result.get('errorCode') or '', msg=result.get('message') or '')
            errors = result.get('errors') or []
            if errors:
                body += '<ul>%s</ul>' % ''.join(
                    '<li><b>%s</b>: %s — %s</li>' % (
                        err.get('field') or err.get('rule') or '',
                        err.get('message') or '', err.get('fix') or '')
                    for err in errors)
        self.message_post(body=body)

    def action_einv_reset(self):
        """Clear the outcome so a stuck document can be pushed again.

        Only for a document that is not locked on the platform — a submitted
        invoice is answered with ALREADY_SUBMITTED and never overwritten.
        """
        for move in self:
            if move.einv_locked:
                raise UserError(_(
                    '%s is already submitted on the platform and cannot be reset.',
                    move.display_name))
            move.einv_error_ids.unlink()
            move.write({
                'einv_state': 'not_sent',
                'einv_error_code': False,
                'einv_message': False,
                'einv_peppol_status': False,
            })
        return True

    def action_einv_reload_parties(self):
        """Pull the seller and buyer blocks back from the master data.

        The party fields are stored and hand-editable, so once edited they stop
        tracking the partner. This discards those edits deliberately.
        """
        for move in self:
            if move.einv_locked:
                raise UserError(_(
                    '%s is already submitted on the platform and cannot be '
                    'changed.', move.display_name))
        self.invalidate_recordset([
            fname for fname in self._fields
            if fname.startswith(('einv_seller_', 'einv_buyer_', 'einv_delivery_'))
        ])
        self._compute_einv_seller()
        self._compute_einv_buyer()
        self._compute_einv_delivery()
        return self._einv_notify(
            _('Parties reloaded'),
            _('The seller and buyer blocks were refilled from the company and '
              'the customer.'), 'success')

    def action_einv_open_logs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'einvoicing_extended_rk.action_einvoice_log')
        action['domain'] = [('move_id', '=', self.id)]
        action['context'] = {'default_move_id': self.id}
        return action

    def _einv_notify(self, title, message, kind='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': title, 'message': message, 'type': kind, 'sticky': False},
        }

    # ==================================================================
    # Hooks
    # ==================================================================
    def _post(self, soft=True):
        """Push on post when the company asks for it.

        A push failure must never roll back the posting, so everything is
        caught: the outcome is recorded on the invoice and can be retried.
        """
        posted = super()._post(soft=soft)
        to_push = posted.filtered(
            lambda m: m.move_type in AR_TYPES
            and m.company_id.einv_enabled
            and m.company_id.einv_auto_push
            and m.einv_state in ('not_sent', 'error')
        )
        for move in to_push:
            try:
                move._einv_push()
            except Exception as exc:
                _logger.exception('eInvoice: auto-push failed for %s', move.name)
                move.sudo().write({
                    'einv_state': 'error',
                    'einv_error_code': 'AUTO_PUSH_FAILED',
                    'einv_message': str(exc),
                })
        return posted

    def button_draft(self):
        """Refuse to reopen a document the FTA has already cleared."""
        cleared = self.filtered(lambda m: m.einv_state in ('submitted', 'cleared'))
        if cleared:
            raise UserError(_(
                'These documents have been submitted to the FTA through the '
                'eInvoicing platform and cannot be reset to draft:\n%s\n\n'
                'Issue a credit note instead.',
                '\n'.join(cleared.mapped('display_name'))))
        return super().button_draft()

    @api.model
    def _einv_cron_push_pending(self):
        """Push everything posted but not yet accepted by the platform."""
        moves = self.search([
            ('move_type', 'in', AR_TYPES),
            ('state', '=', 'posted'),
            ('einv_state', 'in', ('not_sent', 'error')),
            ('company_id.einv_enabled', '=', True),
            ('company_id.einv_auto_push', '=', True),
        ], limit=lk.MAX_BATCH_SIZE)
        if not moves:
            return True
        try:
            moves._einv_push()
        except Exception:
            _logger.exception('eInvoice: scheduled push failed')
        return True
