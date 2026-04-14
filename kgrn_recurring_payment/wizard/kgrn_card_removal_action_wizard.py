from odoo import fields, models, _
from odoo.exceptions import UserError


class KgrnCardRemovalActionWizard(models.TransientModel):
    """Internal wizard to approve or deny a customer card removal request,
    or to force-remove a card as an admin action."""

    _name = 'kgrn.card.removal.action.wizard'
    _description = 'Card Removal Action'

    contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Contract',
        required=True,
        readonly=True,
    )
    customer_name = fields.Char(
        string='Customer',
        related='contract_id.customer_id.name',
        readonly=True,
    )
    card_info = fields.Char(
        string='Card',
        compute='_compute_card_info',
    )
    action = fields.Selection(
        selection=[
            ('remove_only', 'Remove Card Only (keep contract in draft)'),
            ('remove_and_cancel', 'Remove Card & Cancel Contract'),
        ],
        string='Action',
        required=True,
        default='remove_only',
    )
    reason = fields.Text(
        string='Internal Note',
        help='Optional note explaining why the card is being removed.',
    )

    def _compute_card_info(self):
        for rec in self:
            c = rec.contract_id
            if c.card_brand and c.card_last4:
                rec.card_info = f'{c.card_brand} •••• {c.card_last4}'
            else:
                rec.card_info = 'No card registered'

    def action_confirm(self):
        self.ensure_one()
        contract = self.contract_id
        if not contract.stripe_payment_method_id:
            raise UserError(_('No payment card is currently registered on this contract.'))

        cancel = self.action == 'remove_and_cancel'
        contract._detach_stripe_card(cancel_contract=cancel)

        if self.reason:
            contract.message_post(
                body=_('Card removal note: %s') % self.reason,
                subtype_xmlid='mail.mt_note',
            )
        return {'type': 'ir.actions.act_window_close'}
