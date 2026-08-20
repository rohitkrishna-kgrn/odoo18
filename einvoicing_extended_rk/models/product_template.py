# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class ProductTemplate(models.Model):
    """Classification a PINT-AE line needs and Odoo does not carry natively.

    ``VAL-ITEM-SAC`` makes the SAC code mandatory on service lines and
    ``VAL-ITEM-CLASS`` makes the HS classification mandatory on goods lines, so
    both belong on the product rather than being retyped per invoice.
    """
    _inherit = 'product.template'

    einv_item_type = fields.Selection(
        lk.ITEM_TYPE_CODES, string='eInvoice Item Type',
        compute='_compute_einv_item_type', store=True, readonly=False,
        help='Goods, Services or Both. Defaults from the product type.',
    )
    einv_sac_code = fields.Char(
        string='Service Accounting Code (SAC)',
        help='Mandatory on Services / Both lines — rule VAL-ITEM-SAC.',
    )
    einv_hs_code = fields.Char(
        string='HS Classification',
        help='Mandatory on Goods / Both lines — rule VAL-ITEM-CLASS.',
    )
    einv_type_of_goods = fields.Char(
        string='Type of Goods or Services',
        help='Platform typeOfGoods lookup value, e.g. DL8.48.3.3.',
    )
    einv_item_standard_id = fields.Char(
        string='Item Standard Identifier',
        help='GTIN / standard item number, sent under scheme 0088.',
    )
    einv_origin_country_id = fields.Many2one(
        'res.country', string='Country of Origin',
        help='Item country of origin, sent on goods lines.',
    )

    @api.depends('type')
    def _compute_einv_item_type(self):
        for product in self:
            if product.einv_item_type:
                continue
            product.einv_item_type = 'S' if product.type == 'service' else 'G'


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _einv_item_dict(self):
        """Classification block for this product, in platform field names."""
        self.ensure_one()
        tmpl = self.product_tmpl_id
        return {
            'itemType': tmpl.einv_item_type or '',
            'serviceAccountingCode': tmpl.einv_sac_code or '',
            'itemClassification': tmpl.einv_hs_code or '',
            'typeOfGoods': tmpl.einv_type_of_goods or '',
            'itemStandardId': tmpl.einv_item_standard_id or self.barcode or '',
            'sellerItemId': self.default_code or '',
            'originCountry': tmpl.einv_origin_country_id.code or '',
        }
