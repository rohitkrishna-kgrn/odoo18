from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .res_partner_credit_hold import CREDIT_HOLD_OVERDUE_DAYS


class CreditHoldOverride(models.Model):
    """A Managing Partner's authorisation to lift a customer's credit hold.

    The hold is released the moment this record is created — it is not a
    standing authorisation for some future project or proposal. The
    underlying arrears are untouched, so the next evaluation (nightly cron,
    a payment reconciliation, or the manual Re-evaluate button) puts the
    hold straight back if the triggering invoices are still overdue by then.
    """
    _name = 'res.partner.credit.hold.override'
    _description = 'Credit Hold Managing Partner Override'
    _order = 'override_date desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        ondelete='cascade', index=True,
    )
    override_date = fields.Datetime(
        string='Authorised On', required=True, readonly=True,
        default=fields.Datetime.now,
    )
    user_id = fields.Many2one(
        'res.users', string='Authorised By', required=True, readonly=True,
        default=lambda self: self.env.user,
    )
    reason = fields.Text(
        string='Override Reason', required=True,
        help="Why this customer's credit hold is being lifted. Recorded "
             "permanently against the customer.",
    )

    # Snapshot of the arrears at the moment of authorisation, so the log shows
    # what the Managing Partner was actually signing off on.
    hold_amount = fields.Monetary(
        string='Overdue At Override', currency_field='currency_id', readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency', related='partner_id.currency_id', readonly=True,
    )
    hold_invoice_count = fields.Integer(
        string='Invoices On Hold At Override', readonly=True,
    )

    @api.constrains('reason')
    def _check_reason(self):
        for override in self:
            if not (override.reason or '').strip():
                raise ValidationError(_(
                    "An override reason is required. Record why this customer's "
                    "credit hold is being lifted."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        # Authorisation is checked here rather than left to record rules so the
        # refusal carries a message that says what the user is missing.
        if not self.env.su and not self.env.user.has_group(
                'account.group_account_manager'):
            raise UserError(_(
                "Only a Managing Partner can override a credit hold. This "
                "authority is carried by the Accounting 'Advisor' access level "
                "— ask an administrator to set Accounting to Advisor on your "
                "user record if this is your responsibility."
            ))

        for vals in vals_list:
            partner = self.env['res.partner'].browse(vals.get('partner_id'))
            if partner:
                if not partner.credit_hold:
                    raise UserError(_(
                        "%s is not on credit hold, so there is nothing to "
                        "override.", partner.display_name,
                    ))
                vals.setdefault('hold_amount', partner.credit_hold_amount)
                vals.setdefault(
                    'hold_invoice_count', len(partner.credit_hold_invoice_ids),
                )

        overrides = super().create(vals_list)
        for override in overrides:
            override._release()
        return overrides

    def _release(self):
        """Lift the hold on `partner_id` right now and log why."""
        self.ensure_one()
        partner = self.partner_id
        cleared = partner.credit_hold_invoice_ids
        partner.write({
            'credit_hold': False,
            'credit_hold_invoice_ids': [fields.Command.clear()],
            'credit_hold_amount': 0.0,
            'credit_hold_max_age_days': 0,
            'credit_hold_date': False,
            'credit_hold_release_date': fields.Datetime.now(),
        })
        partner._credit_hold_log_event('release', cleared, 0.0, 0, silent=False)
        partner.message_post(body=_(
            "<p><b>Credit hold overridden and released by %(user)s.</b></p>"
            "<p>Reason: %(reason)s</p>"
            "<p>The overdue invoices behind the hold have not been settled — "
            "the next evaluation will place the hold again if they are still "
            "more than %(days)s days overdue.</p>",
            user=self.user_id.display_name,
            reason=self.reason,
            days=CREDIT_HOLD_OVERDUE_DAYS,
        ))
        return True
