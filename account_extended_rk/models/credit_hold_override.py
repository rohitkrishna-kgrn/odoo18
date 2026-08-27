from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class CreditHoldOverride(models.Model):
    """A Managing Partner's authorisation to let one blocked record through.

    Single-use by design: the override is consumed by the first project or
    proposal it lets through, and stamps which record that was. It never
    changes `credit_hold` on the customer — the underlying arrears are
    untouched and the next record is blocked again.
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
        help="Why this customer may take on new work despite being on credit "
             "hold. Recorded permanently against the customer.",
    )
    scope = fields.Selection(
        [
            ('project', 'One new project'),
            ('proposal', 'One new proposal'),
            ('any', 'One project or proposal'),
        ],
        string='Applies To', required=True, default='any',
    )
    state = fields.Selection(
        [
            ('available', 'Not Yet Used'),
            ('consumed', 'Used'),
            ('revoked', 'Revoked'),
        ],
        string='Status', required=True, default='available', readonly=True,
    )

    consumed_date = fields.Datetime(string='Used On', readonly=True)
    consumed_by_id = fields.Many2one('res.users', string='Used By', readonly=True)
    consumed_model = fields.Char(string='Record Model', readonly=True)
    consumed_res_id = fields.Integer(string='Record ID', readonly=True)
    consumed_reference = fields.Char(
        string='Project / Proposal', readonly=True,
        help="The record this override let through.",
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
                    "An override reason is required. Record why this customer "
                    "may take on new work while on credit hold."
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
            override.partner_id.message_post(body=_(
                "<p><b>Credit hold override authorised by %(user)s</b> "
                "(%(scope)s).</p><p>Reason: %(reason)s</p>"
                "<p>The credit hold itself remains in force.</p>",
                user=override.user_id.display_name,
                scope=dict(self._fields['scope'].selection)[override.scope],
                reason=override.reason,
            ))
        return overrides

    def action_revoke(self):
        """Withdraw an override that has not been used yet."""
        for override in self:
            if override.state != 'available':
                raise UserError(_(
                    "Only an unused override can be revoked."
                ))
            override.state = 'revoked'
            override.partner_id.message_post(body=_(
                "Credit hold override authorised by %(user)s was revoked by "
                "%(revoker)s before it was used.",
                user=override.user_id.display_name,
                revoker=self.env.user.display_name,
            ))
        return True

    # ------------------------------------------------------------------
    # Consumption
    # ------------------------------------------------------------------

    @api.model
    def _find_available(self, partner, scope):
        """The oldest unused override covering `scope` for this customer."""
        if not partner:
            return self.browse()
        return self.sudo().search([
            ('partner_id', '=', partner.commercial_partner_id.id),
            ('state', '=', 'available'),
            ('scope', 'in', (scope, 'any')),
        ], order='override_date asc', limit=1)

    @api.model
    def _already_consumed_on(self, record):
        """True when an override was already burned on this exact record."""
        return bool(self.sudo().search_count([
            ('state', '=', 'consumed'),
            ('consumed_model', '=', record._name),
            ('consumed_res_id', '=', record.id),
        ]))

    def _consume(self, record):
        """Burn this override on `record` and log what it let through."""
        self.ensure_one()
        self.sudo().write({
            'state': 'consumed',
            'consumed_date': fields.Datetime.now(),
            'consumed_by_id': self.env.user.id,
            'consumed_model': record._name,
            'consumed_res_id': record.id,
            'consumed_reference': record.display_name,
        })
        body = _(
            "<p><b>Created under a credit hold override.</b></p>"
            "<p>Authorised by %(user)s on %(date)s. Reason: %(reason)s</p>",
            user=self.user_id.display_name,
            date=self.override_date,
            reason=self.reason,
        )
        # Logged in both places: on the record so anyone opening it sees why it
        # exists, and on the customer so the credit history is complete.
        record.message_post(body=body)
        self.partner_id.message_post(body=_(
            "<p><b>Credit hold override used.</b></p>"
            "<p>%(ref)s was created by %(actor)s under the override authorised "
            "by %(user)s. Reason: %(reason)s</p>"
            "<p>The credit hold remains in force.</p>",
            ref=record.display_name,
            actor=self.env.user.display_name,
            user=self.user_id.display_name,
            reason=self.reason,
        ))
        return True

    def action_open_record(self):
        self.ensure_one()
        if not (self.consumed_model and self.consumed_res_id):
            raise UserError(_("This override has not been used yet."))
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.consumed_model,
            'res_id': self.consumed_res_id,
            'view_mode': 'form',
        }
