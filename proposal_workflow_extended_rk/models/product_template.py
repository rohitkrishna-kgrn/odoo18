# -*- coding: utf-8 -*-
from odoo import api, fields, models

# The four services the KGRN eInvoicing PDF API prints, by their fixed number.
EINV_PDF_SERVICES = [
    ('1', 'Service 1 - Business Readiness & Gap Analysis'),
    ('2', 'Service 2 - Onboarding & ASP Linking'),
    ('3', 'Service 3 - ERP Development & Integration'),
    ('4', 'Service 4 - Annual Subscription & Support'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_einvoicing_product = fields.Boolean(
        string='eInvoicing Product',
        help="Reporting flag marking this product as part of the eInvoicing "
             "service catalogue. Filterable and groupable in product list views; "
             "it does not change how the proposal is built.")

    einv_pdf_service = fields.Selection(
        EINV_PDF_SERVICES, string='Proposal Document Service',
        help="Which of the four services in the Proposal and Service Engagement "
             "PDFs this product stands for. The fees of every order line on the "
             "same service are added together in the documents.")

    @api.model
    def _einv_pdf_service_list(self):
        """Bullet list of the products to pick, for error messages."""
        products = self.search([('einv_pdf_service', '!=', False)], order='einv_pdf_service, id')
        return '\n'.join('• %s' % product.display_name for product in products)
