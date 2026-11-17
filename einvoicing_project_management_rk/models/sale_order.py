# -*- coding: utf-8 -*-
from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    epm_trn_count = fields.Integer(
        string="E-Invoicing TRNs", compute="_compute_epm_trn_count",
        groups="einvoicing_project_management_rk.group_einvoicing_pm_user")

    def _compute_epm_trn_count(self):
        # Every Phase 1 row on the SE, the same count Pending uses.
        groups = self.env["einvoicing.phase1.project"].sudo()._read_group(
            [("sale_order_id", "in", self.ids)], ["sale_order_id"], ["__count"])
        counts = {order.id: count for order, count in groups}
        for order in self:
            order.epm_trn_count = counts.get(order.id, 0)

    def action_open_epm_dashboard(self):
        self.ensure_one()
        wizard = self.env["einvoicing.so.dashboard"].create({"sale_order_id": self.id})
        return wizard._reopen()
