from odoo import _, models
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _check_line_unlink(self):
        blocked = super()._check_line_unlink()
        if blocked and self.env.user.has_group(
                "sale_order_line_delete_gk.group_delete_so_line"):
            # Core blocks removing a line from any confirmed order, to
            # protect invoice/delivery tracking. Users holding the
            # 'Delete SO Line' right may remove a line that hasn't actually
            # been invoiced or delivered yet; those stay hard-blocked since
            # deleting them would orphan real tracking data.
            blocked = blocked.filtered(
                lambda l: l.invoice_lines or l.qty_delivered)
        return blocked

    def unlink(self):
        for order in self.order_id:
            lines_removed = self.filtered(lambda l: l.order_id == order)
            if order.state != "sale":
                continue
            remaining = (order.order_line - lines_removed).filtered(
                lambda l: not l.display_type)
            removed_real_lines = lines_removed.filtered(
                lambda l: not l.display_type)
            if removed_real_lines and not remaining:
                raise UserError(_(
                    "\"%s\" is a confirmed sale order and must keep at "
                    "least one order line."
                ) % order.name)
        return super().unlink()
