from odoo import api, models, fields, _

from .crm_tag import APPROVED_TAG_DOMAIN
from odoo.exceptions import UserError, ValidationError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Same approved list as the pipeline - see models/crm_tag.py.
    tag_ids = fields.Many2many(domain=APPROVED_TAG_DOMAIN)

    reminder_date = fields.Date(string='Reminder Date')
    advance_amount = fields.Float(string='Advance Amount', default=0.00)
    auto_invoice = fields.Boolean(string="Auto Invoice", default=True)

    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')
    pending_amount = fields.Monetary(string='Pending Amount', compute='_compute_paid_pending', store=True, currency_field='currency_id')

    order_status = fields.Selection(
        [
            ('new', 'New'),
            ('opened', 'Opened'),
            ('closed', 'Closed'),
        ],
        string='Order Status',
        default='new',
        required=True,
    )

    # eInvoicing engagement info (mirrors the opportunity)
    opportunity_einvoicing = fields.Boolean(
        string='Opportunity eInvoicing', compute='_compute_opportunity_einvoicing')
    einvoicing_service = fields.Boolean(
        string='eInvoicing Service', compute='_compute_einvoicing_service',
        store=True, readonly=False,
        help="Automatically enabled (and locked) when the linked opportunity is an "
             "eInvoicing Service opportunity.")
    entity_count = fields.Integer(
        string='Number of Entities',
        help="Typing a number here generates exactly that many entity rows in "
             "the Entities tab. Lowering it removes the surplus rows from the "
             "bottom of the list.")
    entity_ids = fields.One2many(
        'sale.order.entity', 'order_id', string='Entities', copy=True)
    entity_amount_total = fields.Monetary(
        string='Entity Total', compute='_compute_entity_amount_total',
        store=True, currency_field='currency_id',
        help="Sum of the per-entity prices. Printed under the commercial "
             "structure in the proposal PDF; it does not change the order total, "
             "which is driven by the order lines.")

    @api.depends('entity_ids.price')
    def _compute_entity_amount_total(self):
        for order in self:
            order.entity_amount_total = sum(order.entity_ids.mapped('price'))

    @api.constrains('entity_count')
    def _check_entity_count(self):
        for order in self:
            if order.entity_count < 0:
                raise ValidationError(_("Number of Entities cannot be negative."))

    # ------------------------------------------------------------------
    # Number of Entities <-> Entities rows
    # ------------------------------------------------------------------
    def _next_entity_sequence(self):
        """Sequence for the next appended row — always behind the existing ones,
        even after a drag-reorder has renumbered them."""
        self.ensure_one()
        return max(self.entity_ids.mapped('sequence') or [0]) + 10

    def _sync_entity_rows(self):
        """Make the Entities list exactly `entity_count` rows long (server side).

        Surplus rows are dropped from the tail so the entities already filled in
        keep their number.
        """
        Entity = self.env['sale.order.entity']
        for order in self:
            target = max(order.entity_count or 0, 0)
            entities = order.entity_ids
            if len(entities) > target:
                entities[target:].unlink()
            elif len(entities) < target:
                sequence = order._next_entity_sequence()
                Entity.create([
                    {'order_id': order.id, 'sequence': sequence + index * 10}
                    for index in range(target - len(entities))
                ])

    @api.onchange('entity_count')
    def _onchange_entity_count(self):
        """Same sync, but against the form's in-memory rows.

        Assigning a recordset (rather than a command list) is what makes this
        work on an unsaved quotation too: a command list on an origin-less
        record is applied to an empty set and would throw away the rows already
        added in this form.
        """
        for order in self:
            target = max(order.entity_count or 0, 0)
            if order.entity_count != target:
                # A negative reads back as 0 straight away rather than waiting
                # for _check_entity_count to reject it on save.
                order.entity_count = target
            entities = order.entity_ids
            if len(entities) > target:
                order.entity_ids = entities[:target]
            elif len(entities) < target:
                sequence = order._next_entity_sequence()
                for index in range(target - len(entities)):
                    entities |= self.env['sale.order.entity'].new({
                        'order_id': order.id,
                        'sequence': sequence + index * 10,
                    })
                order.entity_ids = entities

    @api.onchange('entity_ids')
    def _onchange_entity_ids(self):
        """Keep the count honest when rows are added or deleted by hand.

        This cannot loop with `_onchange_entity_count`: the onchange engine only
        runs each field's methods once per call (`done` set in
        `web/models/models.py`), and the two agree after one pass anyway.
        """
        for order in self:
            if order.entity_count != len(order.entity_ids):
                order.entity_count = len(order.entity_ids)

    # ------------------------------------------------------------------
    # Annual invoice counts, pulled from the eInvoicing discovery form
    #
    # The form is the single source of truth: the counts are copied across
    # exactly as the client stated them, matched to the quotation's entities by
    # entity name. Nothing is derived, aggregated or estimated here - a row
    # that cannot be matched confidently is left blank and flagged for review.
    # ------------------------------------------------------------------
    discovery_counts_form_id = fields.Many2one(
        'crm.lead.discovery.form', string='Invoice Counts Source',
        readonly=True, copy=False,
        help="The eInvoicing discovery form submission the annual invoice "
             "counts in the Entities tab were read from.")
    discovery_counts_date = fields.Datetime(
        string='Counts Fetched On', readonly=True, copy=False)

    @staticmethod
    def _entity_name_key(name):
        """Names are compared on a normalised key: case and inner spacing
        routinely differ between what the client typed into the discovery form
        and what was typed onto the quotation ("ABC  Pvt Ltd" / "abc pvt ltd").
        Nothing else is normalised - two genuinely different names never match.
        """
        return ' '.join((name or '').split()).casefold()

    @staticmethod
    def _as_invoice_count(value):
        """The submitted value as an int, or None when the form did not carry a
        usable number. Never substitutes a default: a missing count leaves the
        field blank and flags the row, it does not become 0."""
        # Not `value in (None, '', False)`: 0 == False in Python, and a stated
        # count of 0 is a real answer that must survive as 0, not read as
        # "missing".
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, str) and not value.strip():
            return None
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None

    def _discovery_counts_source(self):
        """The submission the counts are read from: the most recently submitted
        eInvoicing discovery form on the linked opportunity."""
        self.ensure_one()
        # sudo: the counts belong to this quotation's own opportunity, but CRM
        # record rules can hide the lead from whoever is preparing the proposal
        # and would silently return an empty form instead of an error.
        lead = self.sudo().opportunity_id
        if not lead:
            raise UserError(_(
                "This quotation is not linked to an opportunity, so there is no "
                "discovery form to read the invoice counts from."))
        form = self.env['crm.lead.discovery.form'].sudo().search(
            [('lead_id', '=', lead.id),
             ('form_type', '=', 'einvoicing'),
             ('state', '=', 'submitted')],
            order='submitted_date desc, id desc', limit=1)
        if not form:
            raise UserError(_(
                "No submitted eInvoicing discovery form was found on the "
                "opportunity %s. The annual invoice counts can only come from "
                "that form, so there is nothing to fetch yet.") % lead.display_name)
        return form

    def action_fetch_discovery_invoice_counts(self):
        """Populate each entity's annual inbound/outbound invoice counts from
        the eInvoicing discovery form, matching on entity name."""
        self.ensure_one()
        if not self.entity_ids:
            raise UserError(_(
                "There are no entities on this quotation yet. Set the Number of "
                "Entities and name them first."))
        form = self._discovery_counts_source()

        # Index the form's Entity Details by normalised name. A name used by
        # more than one block is ambiguous: the values are never merged or
        # picked between, the entity is flagged for review instead.
        by_name = {}
        duplicates = set()
        for answers in form._entity_answers():
            key = self._entity_name_key(answers.get('entityName'))
            if not key:
                continue
            if key in by_name:
                duplicates.add(key)
            else:
                by_name[key] = answers

        matched = review = 0
        used = set()
        for entity in self.entity_ids:
            key = self._entity_name_key(entity.name)
            answers = by_name.get(key)
            if not key or key in duplicates or answers is None:
                entity.write({
                    'inbound_invoice_count': 0,
                    'outbound_invoice_count': 0,
                    'discovery_state': ('ambiguous' if key in duplicates
                                        else 'unmatched'),
                })
                review += 1
                continue

            used.add(key)
            inbound = self._as_invoice_count(answers.get('inboundCount'))
            outbound = self._as_invoice_count(answers.get('outboundCount'))
            if inbound is None or outbound is None:
                # Matched by name, but the form does not carry both numbers -
                # blank and flagged rather than half-populated.
                entity.write({
                    'inbound_invoice_count': 0,
                    'outbound_invoice_count': 0,
                    'discovery_state': 'incomplete',
                })
                review += 1
                continue

            entity.write({
                'inbound_invoice_count': inbound,
                'outbound_invoice_count': outbound,
                'discovery_state': 'matched',
            })
            matched += 1

        self.write({
            'discovery_counts_form_id': form.id,
            'discovery_counts_date': fields.Datetime.now(),
        })

        # Entities the client described that no row on the quotation claims -
        # reported, never auto-added: the quotation's entity list is the
        # proposal's own scope and is not changed here.
        unclaimed = [answers.get('entityName') for key, answers in by_name.items()
                     if key not in used and key not in duplicates]
        message = _("%(matched)s of %(total)s entities matched the discovery form.") % {
            'matched': matched, 'total': len(self.entity_ids)}
        if review:
            message += _(" %s left blank for review.") % review
        if duplicates:
            message += _(" The form repeats %s entity name(s).") % len(duplicates)
        if unclaimed:
            message += _(" Not on this quotation: %s.") % ', '.join(
                name for name in unclaimed if name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning' if (review or unclaimed) else 'success',
                'title': _("Invoice Counts Fetched"),
                'message': message,
                'sticky': bool(review or unclaimed),
            },
        }

    @api.depends('opportunity_id.discovery_form_type')
    def _compute_opportunity_einvoicing(self):
        for order in self:
            order.opportunity_einvoicing = order.opportunity_id.discovery_form_type == 'einvoicing'

    @api.depends('opportunity_id.discovery_form_type')
    def _compute_einvoicing_service(self):
        for order in self:
            # Forced on when the opportunity is an eInvoicing one; otherwise the
            # value stays whatever it already was (manually set).
            order.einvoicing_service = bool(
                order.einvoicing_service or order.opportunity_id.discovery_form_type == 'einvoicing')

    posted_invoice_total = fields.Monetary(
        string="Posted Invoice Total",
        compute="_compute_posted_invoice_total",
        currency_field='currency_id',
    )

    @api.depends('invoice_ids.amount_total', 'invoice_ids.state')
    def _compute_posted_invoice_total(self):
        for order in self:
            total = 0.0
            for inv in order.invoice_ids:
                if inv.state == 'posted':
                    total += inv.amount_total
            order.posted_invoice_total = total

    def action_open_invoice_wizard(self):
        return {
            'name': 'Create Invoice',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.invoice.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            }
        }

    @api.depends('invoice_ids.payment_state', 'amount_total')
    def _compute_paid_pending(self):
        for order in self:
            paid = 0.0
            # Calculate paid amount from invoices
            invoices = order.invoice_ids.filtered(lambda inv: inv.state in ['posted', 'paid'])
            for inv in invoices:
                # inv.amount_residual is unpaid amount, so paid is total - residual
                paid += inv.amount_total - inv.amount_residual

            order.paid_amount = paid
            order.pending_amount = order.amount_total - paid

    # ------------------------------------------------------------------
    # Pipeline stage automation driven by the linked opportunity
    # ------------------------------------------------------------------
    def _set_opportunity_stage(self, stage_xmlid):
        """Move each linked opportunity to the stage given by external id."""
        stage = self.env.ref(stage_xmlid, raise_if_not_found=False)
        if not stage:
            return
        opportunities = self.mapped('opportunity_id').filtered(
            lambda lead: lead.stage_id != stage)
        if opportunities:
            opportunities.write({'stage_id': stage.id})

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        # A count supplied without rows (import, API, server action) still has
        # to produce the rows; the form already sent both and they agree.
        for order, vals in zip(orders, vals_list):
            if 'entity_count' in vals and 'entity_ids' not in vals:
                order._sync_entity_rows()
        proposition = self.env.ref('crm.stage_lead3', raise_if_not_found=False)
        for order in orders:
            lead = order.opportunity_id
            if not lead:
                continue
            # Link the created sale order back onto the pipeline record.
            lead.sale_order_id = order.id
            # A new draft quotation moves its opportunity forward to "Proposition"
            # (only from an earlier stage - never drags it back).
            if (proposition and order.state == 'draft'
                    and lead.stage_id.sequence < proposition.sequence):
                lead.stage_id = proposition.id
            lead._log_journey_event(
                'proposal_created',
                _("Proposal %s created") % order.name,
                order_id=order.id)
        return orders

    def write(self, vals):
        # "Proposal shared" is the moment the quotation leaves draft for sent.
        # Hooking state here catches every route: the send wizard, the portal
        # share link and any server action, which action_quotation_send alone
        # would miss.
        newly_sent = self.env['sale.order']
        if vals.get('state') == 'sent':
            newly_sent = self.filtered(lambda o: o.state != 'sent')
        res = super().write(vals)
        if 'entity_count' in vals and 'entity_ids' not in vals:
            self._sync_entity_rows()
        elif 'entity_ids' in vals and 'entity_count' not in vals:
            # Rows written without a count — keep the count from lying.
            for order in self:
                if order.entity_count != len(order.entity_ids):
                    order.entity_count = len(order.entity_ids)
        for order in newly_sent:
            order.opportunity_id._log_journey_event(
                'proposal_sent',
                _("Proposal %s shared with client") % order.name,
                order_id=order.id)
            order.opportunity_id._journey_on_proposal_sent()
        return res

    @api.constrains('approval_state', 'tag_ids')
    def _check_tag_required_before_approval(self):
        for order in self:
            if order.approval_state != 'draft' and not order.tag_ids:
                raise ValidationError(_(
                    "Please select a Tag (Other Info > Sales) before this "
                    "quotation can leave Draft."))

    def action_submit_for_approval(self):
        for order in self:
            if not order.tag_ids:
                raise UserError(_(
                    "Please select a Tag (Other Info > Sales) before "
                    "submitting this quotation for approval."))
        return super().action_submit_for_approval()

    def action_approve_order(self):
        res = super().action_approve_order()
        # Approved quotation -> opportunity moves to "Service Engagement".
        approved = self.filtered(lambda o: o.approval_state == 'approved')
        approved._set_opportunity_stage(
            'crm_extended_rk.stage_service_engagement')
        for order in approved:
            order.opportunity_id._log_journey_event(
                'proposal_approved',
                _("Proposal %s approved") % order.name,
                order_id=order.id)
        return res

    def action_confirm(self):
        res = super().action_confirm()
        # Confirmed order -> opportunity moves to "Won".
        self._set_opportunity_stage('crm.stage_lead4')
        for order in self:
            order.opportunity_id._log_journey_event(
                'proposal_confirmed',
                _("Order %s confirmed - lead converted") % order.name,
                order_id=order.id)
        return res

    def action_cancel(self):
        res = super().action_cancel()
        # Cancelled order -> opportunity moves to "Lost".
        self._set_opportunity_stage('crm_extended_rk.stage_lost')
        for order in self:
            order.opportunity_id._log_journey_event(
                'proposal_cancelled',
                _("Proposal %s cancelled") % order.name,
                order_id=order.id)
        return res

    # def _create_advance_invoice(self):
    #     self.ensure_one()

    #     if not self.partner_invoice_id:
    #         raise UserError("Please set an invoice address for the customer.")

    #     existing_invoice = self.invoice_ids.filtered(
    #         lambda inv: inv.state == 'draft' and
    #                     inv.amount_total == self.advance_amount and
    #                     inv.invoice_origin == self.name
    #     )
    #     if existing_invoice:
    #         return

    #     income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
    #     if not income_account:
    #         raise UserError("No income account found for advance invoice line.")

    #     # Optionally reference the first order line (if you want to link it)
    #     sale_line = self.order_line[:1]  # You can also create a fake "advance" line if needed

    #     invoice_vals = {
    #         'move_type': 'out_invoice',
    #         'partner_id': self.partner_invoice_id.id,
    #         'invoice_origin': self.name,
    #         'invoice_user_id': self.user_id.id,
    #         'currency_id': self.currency_id.id,
    #         'invoice_payment_term_id': self.payment_term_id.id,
    #         'invoice_line_ids': [(0, 0, {
    #             'name': 'Advance Payment',
    #             'quantity': 1,
    #             'price_unit': self.advance_amount,
    #             'account_id': income_account.id,
    #             'tax_ids': [(6, 0, sale_line.tax_id.ids)] if sale_line else [],
    #             # ✅ Link to Sale Order Line (for reporting)
    #             'sale_line_ids': [(6, 0, sale_line.ids)] if sale_line else [],
    #         })],
    #     }

    #     invoice = self.env['account.move'].create(invoice_vals)
    #     return invoice


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    engagement_start = fields.Date(string='Engagement Start', required=True)
    engagement_end = fields.Date(string='Engagement End', required=True)
    manager_id = fields.Many2one('res.users', string='Manager', required=True)
    deadline = fields.Date(string='Deadline', required=True)
    estimated_hours = fields.Float(string='Estimated Number of Hours', required=True)

    @api.onchange('product_id')
    def _onchange_product_id_fetch_estimated_hours(self):
        if self.product_id:
            self.estimated_hours = self.product_id.product_tmpl_id.estimated_hours  # get from product template

    @api.onchange('manager_id')
    def _onchange_manager_id_dedicated_check(self):
        if self.manager_id and not self.manager_id.is_dedicated_manager:
            self.manager_id = False
            return {
                'warning': {
                    'title': _("Invalid Manager"),
                    'message': _(
                        "Only users designated as Dedicated Project Managers can be "
                        "assigned as the Manager for this quotation line. Please select "
                        "a user with the Dedicated Project Manager permission enabled."
                    ),
                }
            }

    @api.constrains('manager_id')
    def _check_manager_is_dedicated(self):
        for line in self:
            if line.manager_id and not line.manager_id.is_dedicated_manager:
                raise ValidationError(_(
                    "Only users designated as Dedicated Project Managers can be "
                    "assigned as the Manager for this quotation line. Please select "
                    "a user with the Dedicated Project Manager permission enabled."
                ))


class ResUsers(models.Model):
    _inherit = 'res.users'

    is_dedicated_manager = fields.Boolean(string='Dedicated Project Manager', default=False)

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    estimated_hours = fields.Float(string='Estimated Hours')

class ProjectProject(models.Model):
    _inherit = 'project.project'

    estimated_hours = fields.Float(string='Estimated Hours')
