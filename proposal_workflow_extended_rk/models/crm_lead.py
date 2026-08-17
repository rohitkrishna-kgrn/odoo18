# -*- coding: utf-8 -*-
from odoo import api, fields, models

SEQUENCE_CODE = 'crm.lead.reference'


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Pipeline records get a stable human reference of their own — the CRM
    # counterpart to a sale order's S05631 — so a quotation can cite the exact
    # pipeline record it came from.
    crm_ref = fields.Char(
        string='CRM Reference', copy=False, readonly=True, index=True,
        help="Automatically generated pipeline reference, e.g. CRM0746584.")

    # Lets users find a pipeline record by typing its reference into any
    # Opportunity / CRM Pipeline field.
    _rec_names_search = ['name', 'crm_ref', 'partner_name']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('crm_ref'):
                vals['crm_ref'] = self.env['ir.sequence'].next_by_code(SEQUENCE_CODE)
        return super().create(vals_list)

    @api.depends('crm_ref', 'name')
    def _compute_display_name(self):
        super()._compute_display_name()
        for lead in self:
            if lead.crm_ref:
                lead.display_name = f"{lead.crm_ref} - {lead.display_name}"

    def action_assign_crm_ref(self):
        """Backfill the reference on pipeline records created before this module."""
        sequence = self.env['ir.sequence']
        for lead in self.filtered(lambda l: not l.crm_ref):
            lead.crm_ref = sequence.next_by_code(SEQUENCE_CODE)
