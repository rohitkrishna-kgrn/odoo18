# -*- coding: utf-8 -*-
"""Value preparation for the Service Engagement Agreement PDF (pdf.js `seHtml`).

Shares the proposal's service/commercial/formatting helpers through
`report.proposal.mixin`; everything below is what the agreement adds on top.
"""
from markupsafe import Markup

from odoo import api, fields, models

from . import se_content as content


class ReportServiceEngagementMixin(models.AbstractModel):
    _name = 'report.se.mixin'
    _inherit = 'report.proposal.mixin'
    _description = 'Service Engagement Agreement Values'

    @api.model
    def _agreement_clauses(self, order, client_legal, effective_date):
        """pdf.js substitutes the client and the effective date into the clauses."""
        clauses = []
        for index, (title, text) in enumerate(content.AGREEMENT_LIBRARY, start=1):
            body = text.replace('[Client Legal Name]', client_legal or '[Client]')
            body = body.replace('[Date]', effective_date or 'TBD')
            clauses.append({
                'number': index,
                'title': title,
                # The Payment Terms clause carries its own <strong>/<br> markup.
                'text': Markup(body),
            })
        return clauses

    @api.model
    def _se_values(self, order):
        partner = order.partner_id
        company = partner.commercial_partner_id
        client_legal = company.name or partner.name or '[Client]'
        effective = self._fmt_date(order.se_effective_date) or 'TBD'
        services = self._services(order)
        codes = {(service['code'] or '').upper() for service in services}

        address = ', '.join(part for part in (
            company.street, company.street2, company.city,
            company.country_id.name) if part)

        return {
            'agreement_type': order.se_agreement_type or 'Service Engagement Agreement',
            'se_ref': order.name,
            'client_legal': client_legal,
            'client_person': partner.name if partner != company else '',
            'client_email': company.email or partner.email or '',
            'client_address': address,
            'effective_date': effective,
            'duration': order.se_project_duration or 'TBD',
            'currency': order.currency_id.name,
            'clauses': self._agreement_clauses(order, client_legal, effective),
            'services': services,
            'commercial_rows': self._commercial_rows(order),
            'assumptions': content.SE_ASSUMPTIONS,
            # Schedules D and E are gated on their own service codes, exactly as
            # in pdf.js — the S1-S8 catalogue does not trigger them.
            'show_support_model': 'D' in codes,
            'show_rollout': 'E' in codes,
            'support_model': content.SE_SUPPORT_MODEL,
            'rollout_phases': content.SE_ROLLOUT_PHASES,
            'rollout_note': content.SE_ROLLOUT_NOTE,
            'year': fields.Date.context_today(order).year,
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        values = {order.id: self._se_values(order) for order in orders}
        for order in orders:
            values[order.id].update(self._totals(order))
        return {
            'doc_ids': docids,
            'doc_model': 'sale.order',
            'docs': orders,
            'se': values,
            'logo': self._logo_data_url(),
        }


class ReportSeCover(models.AbstractModel):
    _name = 'report.proposal_workflow_extended_rk.report_se_cover'
    _inherit = 'report.se.mixin'
    _description = 'Service Engagement Agreement — cover'


class ReportSeContent(models.AbstractModel):
    _name = 'report.proposal_workflow_extended_rk.report_se_content'
    _inherit = 'report.se.mixin'
    _description = 'Service Engagement Agreement — terms and schedules'
