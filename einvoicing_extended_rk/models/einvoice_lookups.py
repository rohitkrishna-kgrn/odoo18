# -*- coding: utf-8 -*-
"""Static PINT-AE / UAE FTA lookup lists used across the eInvoicing models.

Every list here mirrors a lookup the KGRN platform exposes at
``GET {API_BASE}/spec/lookups/<name>``; they are kept as Python selections so an
invoice can be prepared and validated offline, before any call is made.
"""

# ``invoiceTypeCode`` — the four document types the platform accepts.
INVOICE_TYPE_CODES = [
    ('380', '380 - Tax Invoice'),
    ('381', '381 - Credit Note'),
    ('389', '389 - Self-Billed Invoice'),
    ('261', '261 - Self-Billed Credit Note'),
]

# The two credit-note codes: both require PrecedingInvoiceNumber + reason code.
CREDIT_NOTE_TYPE_CODES = ('381', '261')
# The two self-billed codes (raised by the buyer on the supplier's behalf).
SELF_BILLED_TYPE_CODES = ('389', '261')
# Codes that require PaymentMeansCode (rule AE-PMC).
PAYMENT_MEANS_REQUIRED_CODES = ('380', '389')

# ``transactionType`` — UAE special-supply flags. Default is a plain domestic sale.
TRANSACTION_TYPE_CODES = [
    ('00000000', '00000000 - Standard tax invoice (no special type)'),
    ('10000000', '10000000 - Free trade zone supply'),
    ('01000000', '01000000 - Deemed supply (no consideration)'),
    ('00100000', '00100000 - Profit margin scheme'),
    ('00010000', '00010000 - Summary invoice'),
    ('00001000', '00001000 - Continuous supply'),
    ('00000100', '00000100 - Agent billing on behalf of a principal'),
    ('00000010', '00000010 - Supply through e-commerce'),
    ('00000001', '00000001 - Exports'),
]

# ``creditNoteReason`` — mandatory whenever InvoiceTypeCode is 381 or 261.
CREDIT_NOTE_REASON_CODES = [
    ('DL8.61.1.A', 'DL8.61.1.A - The supply was cancelled'),
    ('DL8.61.1.B', 'DL8.61.1.B - Tax treatment changed due to a change in the nature of the supply'),
    ('DL8.61.1.C', 'DL8.61.1.C - The agreed consideration was altered'),
    ('DL8.61.1.D', 'DL8.61.1.D - Goods or services were returned in full or in part'),
    ('DL8.61.1.E', 'DL8.61.1.E - Tax was charged or treated in error'),
    ('VD', 'VD - Volume discount'),
]

# ``vatCategory`` — UNCL5305 subset used by PINT-AE.
VAT_CATEGORY_CODES = [
    ('S', 'S - Standard rate'),
    ('Z', 'Z - Zero rated'),
    ('E', 'E - Exempt from tax'),
    ('AE', 'AE - VAT reverse charge'),
    ('O', 'O - Services outside scope of tax'),
    ('N', 'N - Standard rate (additional)'),
]

# Categories for which the platform computes line VAT.
VAT_TAXED_CATEGORIES = ('S', 'N')
# Categories that make a tax exemption reason expected.
VAT_EXEMPT_CATEGORIES = ('Z', 'E', 'AE', 'O')

# ``paymentMeans`` — UNTDID 4461 subset. Default 30 (credit transfer).
PAYMENT_MEANS_CODES = [
    ('1', '1 - Instrument not defined'),
    ('10', '10 - In cash'),
    ('20', '20 - Cheque'),
    ('30', '30 - Credit transfer'),
    ('42', '42 - Payment to bank account'),
    ('48', '48 - Bank card'),
    ('49', '49 - Direct debit'),
    ('54', '54 - Credit card'),
    ('55', '55 - Debit card'),
    ('58', '58 - SEPA credit transfer'),
    ('59', '59 - SEPA direct debit'),
    ('68', '68 - Online payment service'),
    ('97', '97 - Clearing between partners'),
]

# ``itemType`` — goods / services / both, drives which of SAC or HS is mandatory.
ITEM_TYPE_CODES = [
    ('G', 'G - Goods'),
    ('S', 'S - Services'),
    ('B', 'B - Both'),
]

# ``billingFrequency``
BILLING_FREQUENCY_CODES = [
    ('DAY', 'DAY - Daily'),
    ('WEE', 'WEE - Weekly'),
    ('MTH', 'MTH - Monthly'),
    ('QUR', 'QUR - Quarterly'),
    ('HYR', 'HYR - Half-yearly'),
    ('ANN', 'ANN - Annually'),
]

# ``allowanceReason`` — UNTDID 5189 (allowance) / 7161 (charge), common subset.
ALLOWANCE_REASON_CODES = [
    ('41', '41 - Bonus for works ahead of schedule'),
    ('42', '42 - Other bonus'),
    ('60', '60 - Manufacturer consumer discount'),
    ('62', '62 - Due to military status'),
    ('63', '63 - Due to work accident'),
    ('64', '64 - Special agreement'),
    ('65', '65 - Production error discount'),
    ('66', '66 - New outlet discount'),
    ('67', '67 - Sample discount'),
    ('68', '68 - End of range discount'),
    ('70', '70 - Incoterm discount'),
    ('71', '71 - Point of sales threshold allowance'),
    ('88', '88 - Material surcharge/deduction'),
    ('95', '95 - Discount'),
    ('100', '100 - Special rebate'),
    ('102', '102 - Fixed long term'),
    ('103', '103 - Temporary'),
    ('104', '104 - Standard'),
    ('105', '105 - Yearly turnover'),
    ('AA', 'AA - Advertising'),
    ('AAA', 'AAA - Telecommunication'),
    ('ABK', 'ABK - Miscellaneous'),
    ('ABL', 'ABL - Additional packaging'),
    ('ADR', 'ADR - Other services'),
    ('FC', 'FC - Freight service'),
    ('PC', 'PC - Packing'),
    ('SH', 'SH - Special handling'),
    ('TV', 'TV - Transportation'),
]

# ``emirate`` — the PINT-AE country subdivision codes, and the Odoo
# ``res.country.state`` codes shipped by ``l10n_ae`` they correspond to.
EMIRATE_CODES = [
    ('AUH', 'AUH - Abu Dhabi'),
    ('DXB', 'DXB - Dubai'),
    ('SHJ', 'SHJ - Sharjah'),
    ('AJM', 'AJM - Ajman'),
    ('UAQ', 'UAQ - Umm Al Quwain'),
    ('RAK', 'RAK - Ras Al Khaimah'),
    ('FUJ', 'FUJ - Fujairah'),
]

# l10n_ae state code -> PINT-AE emirate code.
ODOO_STATE_TO_EMIRATE = {
    'AZ': 'AUH',
    'DU': 'DXB',
    'SH': 'SHJ',
    'AJ': 'AJM',
    'UQ': 'UAQ',
    'RK': 'RAK',
    'RAK': 'RAK',
    'FU': 'FUJ',
}

# ``buyerLegalRegType`` — the identifier the buyer is registered under.
LEGAL_REG_TYPE_CODES = [
    ('TL', 'TL - Trade Licence'),
    ('CL', 'CL - Commercial Licence'),
    ('CN', 'CN - Company Number'),
    ('OTH', 'OTH - Other'),
]

# UN/ECE Rec 20 codes for the Odoo units of measure shipped out of the box.
# Anything not matched here falls back to C62 (one / piece).
DEFAULT_UOM_UNECE_CODES = {
    'uom.product_uom_unit': 'C62',
    'uom.product_uom_dozen': 'DZN',
    'uom.product_uom_kgm': 'KGM',
    'uom.product_uom_gram': 'GRM',
    'uom.product_uom_ton': 'TNE',
    'uom.product_uom_lb': 'LBR',
    'uom.product_uom_oz': 'ONZ',
    'uom.product_uom_day': 'DAY',
    'uom.product_uom_hour': 'HUR',
    'uom.product_uom_minute': 'MIN',
    'uom.product_uom_meter': 'MTR',
    'uom.product_uom_km': 'KMT',
    'uom.product_uom_cm': 'CMT',
    'uom.product_uom_millimeter': 'MMT',
    'uom.product_uom_mile': 'SMI',
    'uom.product_uom_foot': 'FOT',
    'uom.product_uom_yard': 'YRD',
    'uom.product_uom_inch': 'INH',
    'uom.product_uom_litre': 'LTR',
    'uom.product_uom_cubic_meter': 'MTQ',
    'uom.product_uom_cubic_foot': 'FTQ',
    'uom.product_uom_cubic_inch': 'INQ',
    'uom.product_uom_gal': 'GLL',
    'uom.product_uom_floz': 'OZA',
    'uom.product_uom_qt': 'QT',
    'uom.product_uom_kwh': 'KWH',
}

# ``mimeCode`` values accepted for attachments.
ATTACHMENT_MIME_CODES = (
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/msword',
    'application/vnd.ms-excel',
)

# Per-invoice ``errorCode`` values returned inside ``results[]``.
RESULT_ERROR_CODES = [
    ('MISSING_KEY', 'Missing idempotency key'),
    ('VALIDATION_FAILED', 'PINT-AE validation failed'),
    ('PEPPOL_REJECTED', 'Rejected by the Access Point'),
    ('ALREADY_SUBMITTED', 'Already submitted'),
    ('INVALID_ITEM', 'Invalid item'),
    ('EMPTY_PAYLOAD', 'Empty payload'),
    ('BATCH_TOO_LARGE', 'Batch too large'),
    ('SERVER_ERROR', 'Server error'),
]

# A batch push is capped by the platform at 200 invoices.
MAX_BATCH_SIZE = 200
