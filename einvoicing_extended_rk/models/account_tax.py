# -*- coding: utf-8 -*-
from odoo import api, fields, models

from . import einvoice_lookups as lk


class AccountTax(models.Model):
    """Carry the PINT-AE VAT category on the tax, so lines derive it."""
    _inherit = 'account.tax'

    einv_vat_category = fields.Selection(
        lk.VAT_CATEGORY_CODES, string='eInvoice VAT Category',
        compute='_compute_einv_vat_category', store=True, readonly=False,
        help='UNCL5305 category sent per line. S standard, Z zero-rated, '
             'E exempt, AE reverse charge, O outside scope, N standard '
             'additional. VAT is computed by the platform for S and N only.',
    )
    einv_exemption_reason_code = fields.Char(
        string='Tax Exemption Reason Code',
        help='Expected on Z / E / AE / O lines.',
    )
    einv_exemption_reason = fields.Char(string='Tax Exemption Reason')

    @api.depends('amount', 'amount_type')
    def _compute_einv_vat_category(self):
        """A percentage tax above zero is standard rated; zero percent is Z.

        Exempt, reverse charge and out-of-scope cannot be told apart from the
        rate alone, so they stay a manual choice on the tax.
        """
        for tax in self:
            if tax.einv_vat_category:
                continue
            if tax.amount_type == 'percent' and tax.amount > 0:
                tax.einv_vat_category = 'S'
            else:
                tax.einv_vat_category = 'Z'

    def _einv_rate(self):
        """The percentage to send as vatRate."""
        self.ensure_one()
        return self.amount if self.amount_type == 'percent' else 0.0
