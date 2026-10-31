from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import format_date


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            order._check_duplicate_proposal(_("This quotation cannot be created"))
        return orders

    def write(self, vals):
        """Refuse a save that turns a quotation into a duplicate.

        Covers lines added after the first save and a change of customer.
        Only clashes the save introduces are refused, so quotations that were
        already duplicates before this module stay editable.
        """
        if not {'order_line', 'partner_id'} & set(vals):
            return super().write(vals)
        watched = self.filtered(
            lambda o: o.state in ('draft', 'sent') and o._duplicate_check_applies())
        before = {order.id: order._find_duplicate_proposal_lines() for order in watched}
        res = super().write(vals)
        for order in watched:
            added = order._find_duplicate_proposal_lines() - before[order.id]
            if added:
                order._raise_duplicate_proposal(added, _("This change cannot be saved"))
        return res

    def action_download_proposal(self):
        self.ensure_one()
        self._check_duplicate_proposal(
            _("The proposal for %s cannot be generated", self.name))
        return super().action_download_proposal()

    def action_submit_for_approval(self):
        for order in self:
            order._check_duplicate_proposal(
                _("%s cannot be submitted for approval", order.name))
        return super().action_submit_for_approval()

    def _duplicate_check_applies(self):
        """Renewals are exempt: Renew (sale_renewal_rk) copies the previous
        order's lines and engagement dates as they are, by design."""
        self.ensure_one()
        return self.new_renewed not in ('renewed', 'partially_renewed')

    def _proposal_service_lines(self):
        """Lines that carry a service and an engagement period."""
        return self.order_line.filtered(
            lambda line: line.product_id and not line.display_type
            and not line.is_downpayment
            and line.engagement_start and line.engagement_end)

    def _find_duplicate_proposal_lines(self):
        """Lines of earlier proposals for the same customer and service.

        Only earlier quotations that are still open and not yet approved
        (Draft or To Approve) count. Once a proposal is approved - or
        confirmed - the same customer and service can be quoted again. Such
        an open line is a duplicate when its engagement period overlaps
        (both ends inclusive), or - whatever the dates - when its engagement
        has not ended yet. Open quotations whose period is over (old drafts
        that were never closed) do not block.

        Only quotations created before this one count, so the first proposal
        always goes through and a later copy stays blocked until the first is
        approved or cancelled. Customer is matched at company level (child_of the
        commercial partner), so a quotation raised for a contact person still
        collides with one raised for the company. Searched with sudo: the
        Services menus only show a salesperson their own quotations, but a
        duplicate raised by a colleague must still be caught.
        """
        self.ensure_one()
        Line = self.env['sale.order.line'].sudo()
        duplicates = Line.browse()
        customer = self.partner_id.commercial_partner_id
        if not customer:
            return duplicates
        today = fields.Date.context_today(self)
        for line in self._proposal_service_lines():
            duplicates |= Line.search([
                ('order_id', '<', self.id),
                ('order_id.state', 'in', ('draft', 'sent')),
                ('order_id.approval_state', '!=', 'approved'),
                ('order_id.partner_id', 'child_of', customer.id),
                ('product_id', '=', line.product_id.id),
                ('display_type', '=', False),
                '|',
                '&', ('engagement_start', '<=', line.engagement_end),
                     ('engagement_end', '>=', line.engagement_start),
                ('engagement_end', '>=', today),
            ])
        return duplicates

    def _check_duplicate_proposal(self, blocked):
        self.ensure_one()
        if not self._duplicate_check_applies():
            return
        duplicates = self._find_duplicate_proposal_lines()
        if duplicates:
            self._raise_duplicate_proposal(duplicates, blocked)

    def _raise_duplicate_proposal(self, duplicates, blocked):
        states = dict(self._fields['state']._description_selection(self.env))
        rows = []
        for line in duplicates.sorted(lambda l: (l.order_id.name, l.product_id.display_name)):
            order = line.order_id
            rows.append(_(
                "• %(order)s (%(state)s, %(salesperson)s): %(service)s, %(start)s – %(end)s",
                order=order.name,
                state=states.get(order.state, order.state),
                salesperson=order.user_id.name or _("no salesperson"),
                service=line.product_id.display_name,
                start=format_date(self.env, line.engagement_start),
                end=format_date(self.env, line.engagement_end),
            ))
        raise UserError(_(
            "Duplicate proposal: %(customer)s already has a proposal for the same "
            "service. %(blocked)s.\n\n%(rows)s",
            customer=self.partner_id.commercial_partner_id.display_name,
            blocked=blocked,
            rows="\n".join(rows),
        ))
