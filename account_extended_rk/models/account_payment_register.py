from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        # account.move's action_force_register_payment already blocks the
        # 'Register Payment' button for an invoice with no follow-up logged,
        # but that only guards how the wizard is normally opened. This wizard
        # can also be created and driven straight through the ORM/API without
        # ever going through that button, so the same check is re-applied
        # here, against the invoices actually being settled, right before the
        # payment is created -- the one place this rule cannot be bypassed.
        self.line_ids.move_id._check_followup_required_for_payment()
        return super().action_create_payments()
