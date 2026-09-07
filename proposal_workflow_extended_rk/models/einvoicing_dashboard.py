# -*- coding: utf-8 -*-
"""Data behind the eInvoicing dashboard (OWL client action)."""
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

STALE_DAYS = 7

# Approving a quotation renames it in place, keeping the number and swapping the
# prefix: S07877 becomes SE07877 (sale_order_approval.SaleOrder.action_approve_
# order). The number on the record is therefore the conversion marker the sales
# team reads, and this is what splits the dashboard's two buckets.
SE_NAME_RE = re.compile(r'^\s*SE\d', re.IGNORECASE)

# Each dashboard scope has its own access checkbox. 'einvoicing' covers the
# eInvoicing service catalogue; 'other' is its exact complement, so the two
# dashboards together partition the pipeline with no overlap.
SCOPE_GROUPS = {
    'einvoicing': 'proposal_workflow_extended_rk.group_einvoicing_dashboard',
    'other': 'proposal_workflow_extended_rk.group_other_services_dashboard',
}


class EinvoicingDashboard(models.AbstractModel):
    _name = 'einvoicing.dashboard'
    _description = 'eInvoicing Dashboard'

    # ── access ────────────────────────────────────────────────────────────
    @api.model
    def _check_access(self, scope='einvoicing'):
        if self.env.su:
            return
        group = SCOPE_GROUPS.get(scope, SCOPE_GROUPS['einvoicing'])
        if not self.env.user.has_group(group):
            raise AccessError(_(
                "You do not have access to this dashboard. Ask an administrator "
                "to tick the matching dashboard checkbox on your user record "
                "(Settings > Users > Access Rights)."))

    # ── which pipeline records count as eInvoicing ────────────────────────
    @api.model
    def _lead_domain(self, date_from, date_to, salesperson_id, scope='einvoicing'):
        """Pipeline records for one scope.

        eInvoicing: the opportunity is an eInvoicing discovery, or one of its
        quotations carries a product flagged as an eInvoicing product.
        Other: everything else in the pipeline — the negation of the above.
        """
        einvoicing = [
            '|',
            ('discovery_form_type', '=', 'einvoicing'),
            ('order_ids.order_line.product_id.is_einvoicing_product', '=', True),
        ]
        domain = [('type', '=', 'opportunity')]
        domain += (['!'] + einvoicing) if scope == 'other' else einvoicing
        if date_from:
            domain.append(('create_date', '>=', fields.Date.to_date(date_from)))
        if date_to:
            domain.append((
                'create_date', '<=',
                fields.Datetime.to_datetime(fields.Date.to_date(date_to)) + timedelta(days=1)))
        if salesperson_id:
            domain.append(('user_id', '=', int(salesperson_id)))
        return domain

    @api.model
    def _last_activity(self, lead):
        """Most recent trace of work on the record: a chatter message, a logged
        activity, or failing both the moment it was created."""
        dates = []
        message = self.env['mail.message'].search(
            [('model', '=', 'crm.lead'), ('res_id', '=', lead.id)],
            order='date desc', limit=1)
        if message.date:
            dates.append(message.date)
        if lead.stage_reason_ids:
            dates.append(max(lead.stage_reason_ids.mapped('date')))
        if lead.create_date:
            dates.append(lead.create_date)
        return max(dates) if dates else False

    # ── proposal vs agreement ─────────────────────────────────────────────
    @api.model
    def _split_orders(self, orders):
        """Split a pipeline record's live orders into proposals and agreements.

        The split follows the conversion, not the paperwork: a quotation counts
        as a proposal for exactly as long as its number still reads ``Sxxxxx``,
        and moves to the agreement side the moment approval renames it to
        ``SExxxxx``. The two buckets are exclusive by construction, so a
        converted order can never be counted — or valued — on both sides.

        Cancelled orders belong to neither.
        """
        live = orders.filtered(lambda o: o.state != 'cancel')
        agreements = live.filtered(lambda o: SE_NAME_RE.match(o.name or ''))
        return live - agreements, agreements

    # ── payload ───────────────────────────────────────────────────────────
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, salesperson_id=None,
                           scope='einvoicing'):
        self._check_access(scope)
        leads = self.env['crm.lead'].search(
            self._lead_domain(date_from, date_to, salesperson_id, scope),
            order='create_date desc')

        now = fields.Datetime.now()
        currency = self.env.company.currency_id
        rows = []
        for lead in leads:
            proposals, agreements = self._split_orders(lead.order_ids)
            last = self._last_activity(lead)
            days = (now - last).days if last else False
            rows.append({
                'id': lead.id,
                'crm_ref': lead.crm_ref or '',
                'name': lead.name,
                'partner': lead.partner_id.display_name or lead.partner_name or '',
                'stage': lead.stage_id.name or '',
                'salesperson': lead.user_id.name or _('Unassigned'),
                'expected_revenue': lead.expected_revenue,
                'proposal_names': proposals.mapped('name'),
                'proposal_ids': proposals.ids,
                'proposal_count': len(proposals),
                'proposal_value': sum(proposals.mapped('amount_total')),
                'agreement_names': agreements.mapped('name'),
                'agreement_ids': agreements.ids,
                'agreement_count': len(agreements),
                'agreement_value': sum(agreements.mapped('amount_total')),
                'proposal_doc': bool(proposals.filtered('proposal_generated_on')),
                'agreement_doc': bool(agreements.filtered('se_generated_on')),
                'last_activity': fields.Datetime.to_string(last) if last else '',
                'days_since_activity': days,
                'is_stale': bool(days is not False and days > STALE_DAYS),
            })

        stale = [r for r in rows if r['is_stale']]
        return {
            'rows': rows,
            'kpis': {
                'leads': len(rows),
                # The two money boxes read their own side of the split: Expected
                # Value is what the open Sxxxxx quotations are worth, Order Value
                # what the converted SExxxxx engagements are worth. Together they
                # still add up to the pipeline's total live order value.
                'pipeline_value': sum(r['proposal_value'] for r in rows),
                'order_value': sum(r['agreement_value'] for r in rows),
                'proposals': sum(r['proposal_count'] for r in rows),
                'agreements': sum(r['agreement_count'] for r in rows),
                'stale': len(stale),
            },
            'salespersons': [
                {'id': user.id, 'name': user.name}
                for user in self.env['crm.lead'].search(
                    [('type', '=', 'opportunity')]).mapped('user_id').sorted('name')
            ],
            'currency': currency.symbol or currency.name,
            'stale_days': STALE_DAYS,
        }

    # ── analytics payload (charts dashboard) ──────────────────────────────
    @api.model
    def _month_buckets(self, date_from, date_to):
        """Ordered YYYY-MM keys spanning the selected range."""
        start = fields.Date.to_date(date_from) if date_from else False
        end = fields.Date.to_date(date_to) if date_to else fields.Date.context_today(self)
        if not start:
            start = end.replace(day=1) - timedelta(days=365)
        buckets, cursor = [], start.replace(day=1)
        while cursor <= end and len(buckets) < 36:
            buckets.append(cursor.strftime('%Y-%m'))
            cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        return buckets

    @api.model
    def get_chart_data(self, date_from=None, date_to=None, salesperson_id=None,
                       scope='einvoicing'):
        self._check_access(scope)
        leads = self.env['crm.lead'].search(
            self._lead_domain(date_from, date_to, salesperson_id, scope))
        proposal_orders, agreement_orders = self._split_orders(leads.order_ids)
        orders = proposal_orders + agreement_orders
        now = fields.Datetime.now()

        # Pipeline by stage — how many records sit where, and what they are worth
        by_stage = {}
        for lead in leads:
            entry = by_stage.setdefault(
                lead.stage_id.name or _('Undefined'),
                {'count': 0, 'value': 0.0, 'sequence': lead.stage_id.sequence})
            entry['count'] += 1
            entry['value'] += lead.expected_revenue
        stage_items = sorted(by_stage.items(), key=lambda kv: kv[1]['sequence'])

        # Order value by salesperson — the signed SExxxxx engagements, so this
        # reads the same Order Value the KPI box does.
        by_person = {}
        for order in agreement_orders:
            name = order.user_id.name or _('Unassigned')
            by_person[name] = by_person.get(name, 0.0) + order.amount_total
        person_items = sorted(by_person.items(), key=lambda kv: kv[1], reverse=True)[:10]

        # Revenue mix across the catalogue that belongs to this scope
        wants_einvoicing = scope != 'other'
        by_service = {}
        for line in orders.mapped('order_line'):
            if line.display_type or not line.product_id:
                continue
            if line.product_id.is_einvoicing_product != wants_einvoicing:
                continue
            label = line.product_id.default_code or line.product_id.name
            by_service[label] = by_service.get(label, 0.0) + line.price_subtotal
        service_items = sorted(by_service.items(), key=lambda kv: kv[1], reverse=True)

        # Month-by-month: new pipeline records against agreement value booked
        months = self._month_buckets(date_from, date_to)
        lead_series = dict.fromkeys(months, 0)
        value_series = dict.fromkeys(months, 0.0)
        for lead in leads:
            key = fields.Datetime.to_datetime(lead.create_date).strftime('%Y-%m')
            if key in lead_series:
                lead_series[key] += 1
        for order in agreement_orders:
            if not order.date_order:
                continue
            key = fields.Datetime.to_datetime(order.date_order).strftime('%Y-%m')
            if key in value_series:
                value_series[key] += order.amount_total

        # Conversion funnel: where the pipeline stands right now. "Proposal Sent"
        # and "Agreement" are the two sides of the split, so a record sits in one
        # or the other — never both — and Agreement can exceed Proposal Sent once
        # most quotations have converted.
        proposal_ids, agreement_ids = set(proposal_orders.ids), set(agreement_orders.ids)
        with_order = leads.filtered(
            lambda l: not (proposal_ids | agreement_ids).isdisjoint(l.order_ids.ids))
        with_proposal = leads.filtered(lambda l: not proposal_ids.isdisjoint(l.order_ids.ids))
        with_se = leads.filtered(lambda l: not agreement_ids.isdisjoint(l.order_ids.ids))
        won = leads.filtered(lambda l: l.stage_id.is_won)

        # Activity health
        stale = 0
        for lead in leads:
            last = self._last_activity(lead)
            if last and (now - last).days > STALE_DAYS:
                stale += 1

        return {
            'stage': {
                'labels': [name for name, _v in stage_items],
                'counts': [v['count'] for _n, v in stage_items],
                'values': [round(v['value'], 2) for _n, v in stage_items],
            },
            'salesperson': {
                'labels': [name for name, _v in person_items],
                'values': [round(value, 2) for _n, value in person_items],
            },
            'service': {
                'labels': [name for name, _v in service_items],
                'values': [round(value, 2) for _n, value in service_items],
            },
            'trend': {
                'labels': months,
                'leads': [lead_series[m] for m in months],
                'values': [round(value_series[m], 2) for m in months],
            },
            'funnel': {
                'labels': [_('Pipeline'), _('Quoted'), _('Proposal Sent'),
                           _('Agreement'), _('Won')],
                'values': [len(leads), len(with_order), len(with_proposal),
                           len(with_se), len(won)],
            },
            'activity': {
                'labels': [_('Active (last %sd)') % STALE_DAYS,
                           _('No activity > %sd') % STALE_DAYS],
                'values': [len(leads) - stale, stale],
            },
            'currency': self.env.company.currency_id.symbol or self.env.company.currency_id.name,
            'salespersons': [
                {'id': user.id, 'name': user.name}
                for user in self.env['crm.lead'].search(
                    [('type', '=', 'opportunity')]).mapped('user_id').sorted('name')
            ],
        }
