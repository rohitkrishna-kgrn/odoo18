# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class ResPartner(models.Model):
    """PINT-AE buyer / seller identity fields that Odoo has no home for."""
    _inherit = 'res.partner'

    einv_peppol_scheme = fields.Char(
        string='Peppol Scheme ID', default='0235',
        help='Scheme identifier for the electronic address — 0235 is the UAE '
             'TRN scheme. Sent as BuyerSchemeidentifier.',
    )
    einv_peppol_id = fields.Char(
        string='Peppol Electronic Address',
        compute='_compute_einv_peppol_id', store=True, readonly=False,
        help='The partner Peppol participant id — the RECEIVER of the '
             'transmission. This is not the TRN: scheme + address together '
             'form the UID (0235 + 1010101012 -> 0235:1010101012). When it is '
             'empty the platform falls back to the TRN.',
    )
    einv_buyer_identifier = fields.Char(
        string='Buyer Identifier',
        help='Your own customer reference for this partner (BuyerIdentifier).',
    )
    einv_legal_reg_type = fields.Selection(
        lk.LEGAL_REG_TYPE_CODES, string='Legal Registration Type', default='TL',
    )
    einv_legal_reg_id = fields.Char(string='Legal Registration Identifier')
    einv_trade_license = fields.Char(string='Commercial / Trade Licence')
    einv_emirates_id = fields.Char(string='eInvoice Emirates ID')
    einv_passport = fields.Char(string='eInvoice Passport Number')
    einv_passport_country_id = fields.Many2one(
        'res.country', string='Passport Issuing Country')
    einv_cabinet_decision = fields.Char(string='Cabinet Decision')
    einv_authority_name = fields.Char(string='Issuing Authority')
    einv_emirate_code = fields.Char(
        string='Emirate Code', compute='_compute_einv_emirate_code',
        help='PINT-AE country subdivision code derived from the state on the '
             'address (AUH, DXB, SHJ, AJM, UAQ, RAK, FUJ).',
    )

    @api.depends('peppol_endpoint', 'vat')
    def _compute_einv_peppol_id(self):
        """Default the Peppol address from the Odoo endpoint, else the TRN."""
        for partner in self:
            if partner.einv_peppol_id:
                continue
            partner.einv_peppol_id = (
                partner.peppol_endpoint or (partner.vat or '').replace(' ', '') or False)

    @api.depends('state_id', 'state_id.einv_emirate_code', 'state_id.code')
    def _compute_einv_emirate_code(self):
        for partner in self:
            state = partner.state_id
            partner.einv_emirate_code = (
                state.einv_emirate_code
                or lk.ODOO_STATE_TO_EMIRATE.get((state.code or '').upper())
                or False
            )

    def _einv_address_dict(self, prefix):
        """Address block for a party, keyed with the platform's field names.

        ``prefix`` is ``Buyer``, ``Seller`` or ``DeliverTo`` — the three parties
        that share the same address shape.
        """
        self.ensure_one()
        return {
            '%sAddressLine1' % prefix: self.street or '',
            '%sAddressLine2' % prefix: self.street2 or '',
            '%sCity' % prefix: self.city or '',
            '%sCountrySubdivision' % prefix: self.einv_emirate_code or '',
            '%sPostalZone' % prefix: self.zip or '',
            '%sCountryCode' % prefix: self.country_id.code or 'AE',
        }
