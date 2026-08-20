# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class AccountMoveLine(models.Model):
    """PINT-AE ``items[]`` fields on the invoice line."""
    _inherit = 'account.move.line'

    einv_item_name = fields.Char(
        string='Item Name', compute='_compute_einv_item_fields',
        store=True, readonly=False,
        help='Sent as items[].name. Defaults to the product name; the line '
             'description is sent separately as items[].description.')
    einv_line_identifier = fields.Char(
        string='Line Identifier',
        help='InvoiceLineIdentifier. Defaults to the line position.',
    )
    einv_item_type = fields.Selection(
        lk.ITEM_TYPE_CODES, string='Item Type',
        compute='_compute_einv_item_fields', store=True, readonly=False,
        help='Goods, Services or Both. Drives whether the SAC code or the HS '
             'classification is mandatory.',
    )
    einv_sac_code = fields.Char(
        string='SAC Code', compute='_compute_einv_item_fields',
        store=True, readonly=False,
        help='Service Accounting Code — mandatory on Services / Both lines '
             '(rule VAL-ITEM-SAC).',
    )
    einv_hs_code = fields.Char(
        string='HS Classification', compute='_compute_einv_item_fields',
        store=True, readonly=False,
        help='Mandatory on Goods / Both lines (rule VAL-ITEM-CLASS).',
    )
    einv_type_of_goods = fields.Char(
        string='Type of Goods/Services', compute='_compute_einv_item_fields',
        store=True, readonly=False)
    einv_item_standard_id = fields.Char(
        string='Item Standard Identifier', compute='_compute_einv_item_fields',
        store=True, readonly=False)
    einv_buyer_item_id = fields.Char(string="Buyer's Item Identifier")
    einv_seller_item_id = fields.Char(
        string="Seller's Item Identifier", compute='_compute_einv_item_fields',
        store=True, readonly=False)
    einv_origin_country_id = fields.Many2one(
        'res.country', string='Country of Origin',
        compute='_compute_einv_item_fields', store=True, readonly=False)
    einv_attribute_name = fields.Char(string='Item Attribute Name')
    einv_attribute_value = fields.Char(string='Item Attribute Value')

    einv_vat_category = fields.Selection(
        lk.VAT_CATEGORY_CODES, string='VAT Category',
        compute='_compute_einv_vat', store=True, readonly=False)
    einv_vat_rate = fields.Float(
        string='VAT Rate %', digits=(16, 4),
        compute='_compute_einv_vat', store=True, readonly=False)
    einv_tax_exemption_reason_code = fields.Char(
        string='Tax Exemption Reason Code',
        compute='_compute_einv_vat', store=True, readonly=False)
    einv_tax_exemption_reason = fields.Char(
        string='Tax Exemption Reason',
        compute='_compute_einv_vat', store=True, readonly=False)

    einv_base_quantity = fields.Float(
        string='Price Base Quantity', default=1.0, digits='Product Unit of Measure',
        help='Item Price Base Quantity — the number of units the net price '
             'applies to. Line net is qty x (unitPrice / baseQuantity).',
    )
    einv_gross_price = fields.Float(
        string='Gross Price', digits='Product Price',
        help='Item gross price before the price discount.',
    )
    einv_price_discount = fields.Float(
        string='Price Discount', digits='Product Price',
        compute='_compute_einv_price_discount', store=True, readonly=False,
        help='Item price discount — gross price less net price.',
    )
    einv_order_line_id = fields.Char(
        string='Order Line Reference',
        help="The buyer's order line id, emitted as OrderLineReference/LineID.",
    )
    einv_line_object_id = fields.Char(string='Line Object Identifier')
    einv_line_object_scheme = fields.Char(
        string='Line Object Scheme',
        help='UNTDID 1153 code — 3 letters, e.g. AWV. A non-1153 value is '
             'dropped by the platform (rule ibr-cl-07).',
    )
    einv_line_object_type_code = fields.Char(
        string='Line Object Document Type Code', default='130')

    einv_allowance_total = fields.Monetary(
        string='Line Allowances / Charges', currency_field='currency_id',
        compute='_compute_einv_allowance_total',
        help='Net effect of this line allowances and charges — charges positive, '
             'allowances negative. They come off the line net (ibr-147). Open '
             'the line to add or edit the individual rows.',
    )
    einv_allowance_ids = fields.One2many(
        'einvoice.allowance', 'move_line_id', string='Line Allowances / Charges',
        help='Discounts and charges that reduce or increase this line net.',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('product_id')
    def _compute_einv_item_fields(self):
        """Inherit the classification from the product, once."""
        for line in self:
            product = line.product_id
            tmpl = product.product_tmpl_id
            if not line.einv_item_type:
                line.einv_item_type = (
                    tmpl.einv_item_type
                    or (line.move_id.company_id.einv_default_item_type if line.move_id else False)
                    or 'S'
                )
            if not line.einv_sac_code:
                line.einv_sac_code = tmpl.einv_sac_code or False
            if not line.einv_hs_code:
                line.einv_hs_code = tmpl.einv_hs_code or False
            if not line.einv_type_of_goods:
                line.einv_type_of_goods = tmpl.einv_type_of_goods or False
            if not line.einv_item_standard_id:
                line.einv_item_standard_id = tmpl.einv_item_standard_id or product.barcode or False
            if not line.einv_seller_item_id:
                line.einv_seller_item_id = product.default_code or False
            if not line.einv_item_name:
                line.einv_item_name = product.name or False
            if not line.einv_origin_country_id:
                line.einv_origin_country_id = tmpl.einv_origin_country_id or False

    @api.depends('tax_ids')
    def _compute_einv_vat(self):
        """Derive the VAT category and rate from the taxes on the line.

        Only the first VAT-bearing tax is considered — PINT-AE carries exactly
        one category per line, so a line with several VAT taxes has to be split.
        """
        for line in self:
            tax = line.tax_ids[:1]
            if not tax:
                line.einv_vat_category = line.einv_vat_category or 'O'
                line.einv_vat_rate = 0.0
                line.einv_tax_exemption_reason_code = line.einv_tax_exemption_reason_code or False
                line.einv_tax_exemption_reason = line.einv_tax_exemption_reason or False
                continue
            line.einv_vat_category = tax.einv_vat_category or 'S'
            line.einv_vat_rate = tax._einv_rate()
            line.einv_tax_exemption_reason_code = tax.einv_exemption_reason_code or False
            line.einv_tax_exemption_reason = tax.einv_exemption_reason or False

    @api.depends('einv_gross_price', 'price_unit')
    def _compute_einv_price_discount(self):
        for line in self:
            if line.einv_gross_price and line.einv_gross_price > line.price_unit:
                line.einv_price_discount = line.einv_gross_price - line.price_unit
            else:
                line.einv_price_discount = line.einv_price_discount or 0.0

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    @api.depends('einv_allowance_ids.amount', 'einv_allowance_ids.charge_indicator')
    def _compute_einv_allowance_total(self):
        for line in self:
            line.einv_allowance_total = sum(
                allowance.amount if allowance.charge_indicator == 'true'
                else -allowance.amount
                for allowance in line.einv_allowance_ids
            )

    def _einv_label(self):
        """Short, single-line name for this line, for use in error messages.

        Line descriptions can be whole paragraphs, which makes an error listing
        unreadable, so the product name wins and anything else is cut at the
        first line break.
        """
        self.ensure_one()
        label = self.product_id.name or (self.name or '').split('\n')[0].strip()
        return (label[:57] + '...') if len(label) > 60 else label

    def _einv_net_unit_price(self):
        """Unit price net of the Odoo line discount.

        Odoo's ``discount`` is a percentage on the line; PINT-AE has no such
        concept on the price, so it is folded into the net price and the
        original price is reported as the gross price.
        """
        self.ensure_one()
        return self.price_unit * (1 - (self.discount or 0.0) / 100.0)

    def _einv_item_payload(self, index):
        """One ``items[]`` entry."""
        self.ensure_one()
        net_price = self._einv_net_unit_price()
        vals = {
            'InvoiceLineIdentifier': self.einv_line_identifier or str(index),
            'description': self.name or (self.product_id.display_name or ''),
            'name': self.einv_item_name or self.product_id.name or (self.name or '')[:80],
            'qty': abs(self.quantity or 0.0),
            'unit': self.product_uom_id.einv_unece_code or 'C62',
            'unitPrice': round(net_price, 4),
            'baseQuantity': self.einv_base_quantity or 1.0,
            'itemType': self.einv_item_type or 'S',
            'vatCategory': self.einv_vat_category or 'S',
            'vatRate': self.einv_vat_rate or 0.0,
        }
        # Gross price + discount are only meaningful together; Odoo's percentage
        # discount is expressed here as the amount taken off the unit price.
        gross = self.einv_gross_price or (self.price_unit if self.discount else 0.0)
        if gross:
            vals['grossPrice'] = round(gross, 4)
            vals['priceDiscount'] = round(
                self.einv_price_discount or (gross - net_price), 4)

        optional = {
            'serviceAccountingCode': self.einv_sac_code,
            'itemClassification': self.einv_hs_code,
            'typeOfGoods': self.einv_type_of_goods,
            'itemStandardId': self.einv_item_standard_id,
            'buyerItemId': self.einv_buyer_item_id,
            'sellerItemId': self.einv_seller_item_id,
            'originCountry': self.einv_origin_country_id.code,
            'attributeName': self.einv_attribute_name,
            'attributeValue': self.einv_attribute_value,
            'orderLineId': self.einv_order_line_id,
            'lineObjectId': self.einv_line_object_id,
            'lineObjectScheme': self.einv_line_object_scheme,
        }
        if self.einv_line_object_id:
            optional['lineObjectTypeCode'] = self.einv_line_object_type_code or '130'
        if self.einv_vat_category in lk.VAT_EXEMPT_CATEGORIES:
            optional['taxExemptionReasonCode'] = self.einv_tax_exemption_reason_code
            optional['taxExemptionReason'] = self.einv_tax_exemption_reason
        vals.update({k: v for k, v in optional.items() if v})

        if self.einv_allowance_ids:
            vals['allowances'] = [a._einv_payload() for a in self.einv_allowance_ids]
        return vals
