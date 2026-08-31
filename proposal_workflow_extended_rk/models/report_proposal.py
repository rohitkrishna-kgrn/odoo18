# -*- coding: utf-8 -*-
"""Value preparation for the eInvoicing Services Proposal PDF.

All formatting the JS original did inline (`toLocaleString`, `toLocaleDateString`,
the fee-structure badge logic, the discovery-snapshot mapping) is done here so
the QWeb template stays a straight transcription of the pdf.js markup.
"""
import base64
import json
import logging
import re

from markupsafe import Markup

from odoo import api, fields, models
from odoo.tools.misc import file_open

from . import proposal_content as content

_logger = logging.getLogger(__name__)
LOGO_PATH = 'proposal_workflow_extended_rk/static/src/img/logo-kgrn.png'

RECURRING_RE = re.compile(r'annual|subscription', re.IGNORECASE)


class ReportProposalMixin(models.AbstractModel):
    """Shared values for both halves of the proposal (see report_paperformat.xml
    for why it is rendered in two passes)."""
    _name = 'report.proposal.mixin'
    _description = 'eInvoicing Services Proposal Values'

    # ── formatting helpers ────────────────────────────────────────────────
    @api.model
    def _fmt_amount(self, value):
        """toLocaleString('en-US', {minimumFractionDigits: 2})"""
        return '{:,.2f}'.format(value or 0.0)

    @api.model
    def _fmt_date(self, value):
        """toLocaleDateString('en-GB', {day:'numeric', month:'long', year:'numeric'})"""
        if not value:
            return None
        return fields.Date.to_date(value).strftime('%-d %B %Y')

    @api.model
    def _bullets(self, text):
        """A textarea becomes one bullet per non-empty line."""
        if not text:
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    @api.model
    def _logo_data_url(self):
        """Embed the logo like pdf.js did — no URL resolution inside wkhtmltopdf."""
        try:
            with file_open(LOGO_PATH, 'rb') as logo:
                return 'data:image/png;base64,' + base64.b64encode(logo.read()).decode()
        except OSError:
            _logger.warning("Proposal logo not found at %s", LOGO_PATH)
            return ''

    # ── discovery snapshot (Section 2) ────────────────────────────────────
    @api.model
    def _discovery_value(self, raw):
        if raw is None or raw == '' or raw == []:
            return None
        if isinstance(raw, bool):
            return 'Yes' if raw else 'No'
        if isinstance(raw, (list, tuple)):
            return ', '.join(str(v) for v in raw) or None
        return str(raw)

    @api.model
    def _discovery_rows(self, order):
        lead = order.crm_pipeline_id or order.opportunity_id
        if not lead:
            return []
        submission = self.env['crm.lead.discovery.form'].search(
            [('lead_id', '=', lead.id), ('state', '=', 'submitted')],
            order='submitted_date desc, id desc', limit=1)
        if not submission or not submission.data:
            return []
        try:
            payload = json.loads(submission.data)
        except (ValueError, TypeError):
            return []
        if not isinstance(payload, dict):
            return []
        rows = []
        for key, label in content.DISCOVERY_LABELS:
            value = self._discovery_value(payload.get(key))
            if value:
                rows.append((label, value))
        return rows

    # ── service narratives (Sections 3-6) ─────────────────────────────────
    @api.model
    def _fee_structure(self, code, name):
        """pdf.js: S6 or an 'annual'/'subscription' name reads as recurring."""
        recurring = (code or '').upper() == 'S6' or bool(RECURRING_RE.search(name or ''))
        return {
            'recurring': recurring,
            'label': 'Annual · Recurring' if recurring else 'One-time / Fixed',
        }

    @api.model
    def _deliverables(self, text):
        """'Title | description' per line; the description half is optional."""
        items = []
        for line in self._bullets(text):
            title, separator, description = line.partition('|')
            items.append({
                'title': title.strip(),
                'desc': description.strip() if separator else
                        'Delivered as part of the agreed scope for this service line.',
            })
        return items

    @api.model
    def _services(self, order):
        services = []
        for narrative in order.proposal_line_ids:
            code = narrative.code or narrative.product_id.default_code or ''
            services.append({
                'code': code,
                'name': narrative.name or narrative.product_id.name,
                'profile': narrative.product_id.description_sale or '',
                'model': self._fee_structure(code, narrative.name)['label'],
                'scope': self._bullets(narrative.scope),
                'methodology': self._bullets(narrative.methodology),
                'deliverables': self._deliverables(narrative.deliverables),
            })
        return services

    # ── commercial structure (Section 10) ─────────────────────────────────
    @api.model
    def _commercial_note(self, line):
        """pdf.js prints a short commercial note here, not the service description.

        Odoo pre-fills a line's description with the product's display name and
        sales description; that already appears in the Service column and in
        Section 4, so it is stripped out. Whatever a salesperson typed on top of
        it is a real note and is kept.
        """
        note = (line.name or '').strip()
        for boilerplate in (line.product_id.display_name,
                            line.product_id.description_sale,
                            line.product_id.name):
            boilerplate = (boilerplate or '').strip()
            if boilerplate and note.startswith(boilerplate):
                note = note[len(boilerplate):].strip()
        return note or '—'

    @api.model
    def _commercial_rows(self, order):
        rows = []
        narrative_by_product = {
            narrative.product_id.id: narrative
            for narrative in order.proposal_line_ids
        }
        for line in order.order_line:
            if line.display_type or not line.product_id:
                continue
            narrative = narrative_by_product.get(line.product_id.id)
            code = (narrative.code if narrative else None) or line.product_id.default_code or ''
            name = (narrative.name if narrative else None) or line.product_id.name
            rows.append({
                'code': code,
                'name': name,
                'fee_structure': self._fee_structure(code, name),
                'fee': self._fmt_amount(line.price_subtotal),
                'notes': self._commercial_note(line),
            })
        return rows

    # ── entity fee breakdown (Section 10, under the totals) ───────────────
    @api.model
    def _entity_rows(self, order):
        """Entity 1..N with their name and fee, in the order shown on the form.

        Numbered here with `enumerate` rather than read off `entity_no`, so the
        PDF stays right even if a row's compute has not been triggered.
        """
        rows = []
        for index, entity in enumerate(order.entity_ids, start=1):
            rows.append({
                'number': index,
                'label': 'Entity %d' % index,
                'name': (entity.name or '').strip() or 'To be confirmed',
                'price': self._fmt_amount(entity.price),
            })
        return rows

    @api.model
    def _totals(self, order):
        gross = sum(
            line.price_unit * line.product_uom_qty
            for line in order.order_line
            if not line.display_type
        )
        discount = gross - order.amount_untaxed
        percentages = {
            line.discount for line in order.order_line
            if not line.display_type and line.discount
        }
        return {
            'subtotal': self._fmt_amount(order.amount_untaxed),
            'discount': self._fmt_amount(discount) if discount > 0.01 else None,
            'discount_percent': (
                '{:g}'.format(percentages.pop()) if len(percentages) == 1 else None
            ),
            'vat': self._fmt_amount(order.amount_tax),
            'total': self._fmt_amount(order.amount_total),
        }

    # ── assembly ──────────────────────────────────────────────────────────
    @api.model
    def _proposal_values(self, order):
        partner = order.partner_id
        company = partner.commercial_partner_id
        services = self._services(order)
        summary = (order.proposal_executive_summary or '').strip() or (
            "KGRN Chartered Accountants is pleased to present this eInvoicing "
            "services proposal to %s. This document sets out our understanding of "
            "the client's requirements, the scope of services recommended, our "
            "delivery approach, and the commercial terms applicable to the "
            "engagement." % (company.name or '')
        )
        values = {
            # Cover title: "<Proposal Name> Proposal".
            'proposal_name': (order.proposal_name or '').strip() or 'eInvoicing Services',
            'company_name': company.name or partner.name or '',
            'person_name': partner.name if partner != company else '',
            'order_ref': order.name,
            'issued': self._fmt_date(order.date_order) or self._fmt_date(fields.Date.today()),
            'valid_until': self._fmt_date(order.validity_date) or 'TBD',
            'currency': order.currency_id.name,
            'exec_summary': summary,
            'exec_tail': content.EXEC_SUMMARY_TAIL,
            'ds_rows': self._discovery_rows(order),
            'services': services,
            'has_deliverables': any(service['deliverables'] for service in services),
            'has_methodology': any(service['methodology'] for service in services),
            'commercial_rows': self._commercial_rows(order),
            'entity_rows': self._entity_rows(order),
            'entity_count': order.entity_count,
            'entity_total': self._fmt_amount(order.entity_amount_total),
            'terms': Markup(order.proposal_terms or content.DEFAULT_TERMS_HTML),
            'salesperson': order.user_id.name or '',
        }
        values.update(self._totals(order))
        return values

    @api.model
    def _get_report_values(self, docids, data=None):
        orders = self.env['sale.order'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'sale.order',
            'docs': orders,
            'proposal': {order.id: self._proposal_values(order) for order in orders},
            'logo': self._logo_data_url(),
            'delivery_phases': content.DELIVERY_PHASES,
            'guiding_principles': content.GUIDING_PRINCIPLES,
            'assumptions': content.ASSUMPTIONS,
            'exclusions': content.EXCLUSIONS,
            'next_steps': content.NEXT_STEPS,
        }


class ReportProposalBleed(models.AbstractModel):
    _name = 'report.proposal_workflow_extended_rk.report_proposal_bleed'
    _inherit = 'report.proposal.mixin'
    _description = 'eInvoicing Services Proposal — cover and closing'


class ReportProposalContent(models.AbstractModel):
    _name = 'report.proposal_workflow_extended_rk.report_proposal_content'
    _inherit = 'report.proposal.mixin'
    _description = 'eInvoicing Services Proposal — content pages'
