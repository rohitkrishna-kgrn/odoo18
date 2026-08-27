from odoo import models, fields, api, _


class CreditHoldEvent(models.Model):
    """Immutable history of every hold placed and every hold released.

    Kept as its own model rather than as chatter alone so the customer's credit
    history can be filtered, grouped and reported on — and so the numbers that
    justified a hold survive the invoices being paid down to zero afterwards.
    """
    _name = 'res.partner.credit.hold.event'
    _description = 'Customer Credit Hold Event'
    _order = 'event_date desc, id desc'

    partner_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        ondelete='cascade', index=True,
    )
    event_type = fields.Selection(
        [('hold', 'Credit Hold Placed'), ('release', 'Credit Hold Released')],
        string='Event', required=True,
    )
    event_date = fields.Datetime(
        string='Date', required=True, default=fields.Datetime.now,
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'credit_hold_event_move_rel', 'event_id', 'move_id',
        string='Invoices',
        help="On a hold: the invoices that triggered it. On a release: the "
             "invoices that had been holding the customer, now cleared.",
    )
    amount = fields.Monetary(
        string='Overdue Amount', currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency', related='partner_id.currency_id', readonly=True,
    )
    max_age_days = fields.Integer(string='Oldest Overdue (Days)')
    detail = fields.Text(
        string='Invoice Detail',
        help="Frozen snapshot of invoice number, overdue amount, due date and "
             "age at the moment of the event.",
    )
    is_backfill = fields.Boolean(
        string='Go-Live Backfill',
        help="Set on the events written by the one-off pass that placed holds "
             "on the customers already in arrears when this policy started. "
             "Those holds were applied silently, with no notification sent.",
    )

    @api.depends('partner_id', 'event_type', 'event_date')
    def _compute_display_name(self):
        for event in self:
            event.display_name = "%s — %s" % (
                event.partner_id.display_name or '',
                dict(self._fields['event_type'].selection).get(event.event_type, ''),
            )
