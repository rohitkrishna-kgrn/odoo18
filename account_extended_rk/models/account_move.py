from odoo import models, api
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _check_sale_line_tasks_completed(self):
        """Validate that all related sale order lines are fully delivered"""
        for move in self:
            if move.move_type != 'out_invoice':
                continue

            for line in move.invoice_line_ids:
                for sale_line in line.sale_line_ids:
                    if sale_line.product_uom_qty != sale_line.qty_delivered:
                        raise UserError(
                            "You can create invoice only all the tasks in project has been completed"
                        )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        # ✅ Bypass for automated creation
        if self.env.context.get('automated_invoice_creation'):
            return records

        records._check_sale_line_tasks_completed()
        return records

    def write(self, vals):
        res = super().write(vals)

        # ✅ Bypass for automated creation
        if self.env.context.get('automated_invoice_creation'):
            return res

        self._check_sale_line_tasks_completed()
        return res
