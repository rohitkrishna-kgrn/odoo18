from odoo import models

from .res_partner import CHECK_SIMILAR_NAME


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _create_customer(self):
        """Convert to Opportunity > Create a new customer."""
        return super(CrmLead, self.with_context(**{CHECK_SIMILAR_NAME: True}))._create_customer()
