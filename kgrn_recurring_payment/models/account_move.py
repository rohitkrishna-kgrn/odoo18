from odoo import models, _


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_apply_existing_payment(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Apply Existing Payment'),
            'res_model': 'kgrn.apply.existing.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_move_id': self.id},
        }
