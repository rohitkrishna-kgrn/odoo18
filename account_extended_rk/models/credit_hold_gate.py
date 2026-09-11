from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .res_partner_credit_hold import CREDIT_HOLD_OVERDUE_DAYS


class ResPartnerCreditHoldGate(models.Model):
    _inherit = 'res.partner'

    def _credit_hold_block(self, description):
        """Gatekeeper for every restricted flow.

        Raises when the customer is on hold. A Managing Partner override
        releases the hold immediately (see credit_hold_override.py), so by
        the time a record can be created there is nothing left to check for
        here beyond the flag itself.
        """
        if not self:
            return

        partner = self.commercial_partner_id
        if not partner.credit_hold:
            return

        raise UserError(_(
            "%(customer)s is on CREDIT HOLD — %(description)s cannot be created.\n\n"
            "%(count)s invoice(s) totalling %(amount)s are more than %(days)s days "
            "past due (oldest %(age)s days), on hold since %(since)s.\n\n"
            "Either clear the outstanding balance, or ask a Managing Partner to "
            "override and release the hold on the customer record "
            "(Credit Hold tab → Override Credit Hold).",
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
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if not partner and vals.get('sale_order_id'):
                partner = self.env['sale.order'].browse(
                    vals['sale_order_id']).partner_id
            if partner:
                partner._credit_hold_block(_("a new project"))

        return super().create(vals_list)


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
        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if partner:
                partner._credit_hold_block(_("a new proposal"))

        return super().create(vals_list)

    def action_submit_for_approval(self):
        # A proposal drafted before the hold landed must not sail through
        # approval afterwards, so submission is gated as well as creation.
        for order in self.filtered(lambda o: o.partner_id):
            order.partner_id._credit_hold_block(_("proposal %s", order.name))
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
