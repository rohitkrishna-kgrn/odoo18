from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .res_partner_credit_hold import CREDIT_HOLD_OVERDUE_DAYS


class ResPartnerCreditHoldGate(models.Model):
    _inherit = 'res.partner'

    def _credit_hold_consume_or_block(self, scope, description):
        """Gatekeeper for every restricted flow.

        Returns the override that should be burned once the record exists, or
        an empty recordset when the customer is not on hold. Raises when the
        customer is on hold and no Managing Partner override is waiting.
        """
        if not self:
            return self.env['res.partner.credit.hold.override']

        partner = self.commercial_partner_id
        if not partner.credit_hold:
            return self.env['res.partner.credit.hold.override']

        override = self.env['res.partner.credit.hold.override']._find_available(
            partner, scope,
        )
        if override:
            return override

        raise UserError(_(
            "%(customer)s is on CREDIT HOLD — %(description)s cannot be created.\n\n"
            "%(count)s invoice(s) totalling %(amount)s are more than %(days)s days "
            "past due (oldest %(age)s days), on hold since %(since)s.\n\n"
            "Either clear the outstanding balance, or ask a Managing Partner to "
            "record an override with a reason on the customer record "
            "(Credit Hold tab → Override Credit Hold). An override authorises one "
            "record only and does not lift the hold.",
            customer=partner.display_name,
            description=description,
            count=len(partner.credit_hold_invoice_ids),
            amount=partner.credit_hold_amount,
            days=CREDIT_HOLD_OVERDUE_DAYS,
            age=partner.credit_hold_max_age_days,
            since=fields.Date.to_date(partner.credit_hold_date) or '-',
        ))


class ProjectProject(models.Model):
    _inherit = 'project.project'

    partner_credit_hold = fields.Boolean(
        string='Customer On Credit Hold',
        related='partner_id.commercial_partner_id.credit_hold',
        readonly=True,
    )
    partner_credit_hold_warning = fields.Char(
        related='partner_id.commercial_partner_id.credit_hold_warning',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Which override (if any) covers each project about to be created.
        # Resolved before super() so a blocked create never touches the
        # database, and consumed after so the log can name the project.
        overrides = []
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if not partner and vals.get('sale_order_id'):
                partner = self.env['sale.order'].browse(
                    vals['sale_order_id']).partner_id
            overrides.append(
                partner._credit_hold_consume_or_block('project', _("a new project"))
                if partner else self.env['res.partner.credit.hold.override']
            )

        projects = super().create(vals_list)

        for project, override in zip(projects, overrides):
            if override:
                override._consume(project)
        return projects


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    partner_credit_hold = fields.Boolean(
        string='Customer On Credit Hold',
        related='partner_id.commercial_partner_id.credit_hold',
        readonly=True,
    )
    partner_credit_hold_warning = fields.Char(
        related='partner_id.commercial_partner_id.credit_hold_warning',
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        overrides = []
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            overrides.append(
                partner._credit_hold_consume_or_block('proposal', _("a new proposal"))
                if partner else self.env['res.partner.credit.hold.override']
            )

        orders = super().create(vals_list)

        for order, override in zip(orders, overrides):
            if override:
                override._consume(order)
        return orders

    def action_submit_for_approval(self):
        # A proposal drafted before the hold landed must not sail through
        # approval afterwards, so submission is gated as well as creation.
        # An override already burned on *this* order still covers it, though —
        # otherwise authorising a proposal would take two overrides, one to
        # draft it and another to submit it.
        Override = self.env['res.partner.credit.hold.override']
        for order in self.filtered(lambda o: o.partner_id):
            if Override._already_consumed_on(order):
                continue
            override = order.partner_id._credit_hold_consume_or_block(
                'proposal', _("proposal %s", order.name),
            )
            if override:
                override._consume(order)
        return super().action_submit_for_approval()

    @api.onchange('partner_id')
    def _onchange_partner_id_credit_hold(self):
        """Warn the moment the customer is picked, before any work is typed in."""
        partner = self.partner_id.commercial_partner_id
        if partner and partner.credit_hold:
            return {
                'warning': {
                    'title': _("Customer On Credit Hold"),
                    'message': partner.credit_hold_warning,
                }
            }


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        """Release a hold as soon as the money lands, not the next morning.

        Hooked here rather than on account.move.write() because payment_state
        is a stored computed field: the ORM writes it straight to the cache
        under env.protecting during recompute, so a write() override never sees
        it. Every payment, refund allocation and manual match does however
        create a partial reconcile.

        Only customers already carrying a hold are re-checked — nothing a
        payment does mid-day can push a fresh invoice past %s days, so placing
        new holds stays the nightly cron's job.
        """ % CREDIT_HOLD_OVERDUE_DAYS
        partials = super().create(vals_list)

        moves = (
            partials.debit_move_id.move_id | partials.credit_move_id.move_id
        )
        partners = moves.mapped('commercial_partner_id').filtered('credit_hold')
        if partners:
            # The search inside the evaluation flushes account.move, which is
            # what forces the pending payment_state recompute to land first.
            partners._credit_hold_evaluate()
        return partials
