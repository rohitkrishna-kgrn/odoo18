from odoo import api, models, fields


class AccountInvoiceFollowupLog(models.Model):
    _name = 'account.invoice.followup.log'
    _description = 'Invoice Follow-up Log'
    _order = 'date desc, id desc'

    move_id = fields.Many2one(
        'account.move',
        string='Invoice',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='Follow-up Date',
        required=True,
        default=fields.Date.context_today,
    )
    method = fields.Selection(
        [
            ('email', 'Email'),
            ('call', 'Call'),
            ('whatsapp', 'WhatsApp'),
        ],
        string='Method',
        required=True,
    )
    response = fields.Text(string='Client Response')
    # Stamped with whoever writes the line and never selectable: the log is
    # an audit trail of who chased the client, so it must not be attributable
    # to another user. Kept out of the client's reach in the view (readonly)
    # and re-forced here so an import, Studio tweak or raw RPC call cannot
    # rewrite it either.
    user_id = fields.Many2one(
        'res.users',
        string='Logged By',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )

    # ------------------------------------------------------------------
    # Reporting handles. Stored so the AR export can group and filter on
    # them; a follow-up never moves to another invoice, so they are written
    # once and never recomputed in anger.
    # ------------------------------------------------------------------
    partner_id = fields.Many2one(
        related='move_id.partner_id', string='Client', store=True, index=True)
    ar_responsible_id = fields.Many2one(
        related='move_id.ar_responsible_id', string='AR Responsible', store=True)
    invoice_date_due = fields.Date(
        related='move_id.invoice_date_due', string='Due Date', store=True)
    aging_bucket = fields.Selection(
        related='move_id.aging_bucket', string='Aging Bucket', store=True)
    amount_residual = fields.Monetary(
        related='move_id.amount_residual', string='Amount Due',
        currency_field='currency_id')
    currency_id = fields.Many2one(related='move_id.currency_id')
    move_state = fields.Selection(related='move_id.state', string='Invoice Status')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # sudo() is left an escape hatch for data migrations and for
            # server code that logs a follow-up on someone else's behalf.
            if not (self.env.su and vals.get('user_id')):
                vals['user_id'] = self.env.user.id
        return super().create(vals_list)

    def write(self, vals):
        if 'user_id' in vals and not self.env.su:
            vals = {k: v for k, v in vals.items() if k != 'user_id'}
        return super().write(vals)
