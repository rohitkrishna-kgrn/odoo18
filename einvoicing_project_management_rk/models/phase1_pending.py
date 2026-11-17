# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class EinvoicingPhase1Pending(models.Model):
    """Approved eInvoicing SEs with entities not yet listed in Phase 1 Projects.

    Total Entities is the number of rows in the SE's Entities tab
    (sale.order.entity). Listed is the number of Phase 1 Project rows on that
    SE, one per TRN. An SE appears while Total Entities is greater than Listed,
    including SEs with no Phase 1 row at all. An SE with an empty Entities tab
    has nothing to compare against and never appears.
    """
    _name = "einvoicing.phase1.pending"
    _description = "E-Invoicing Phase 1 Pending SE"
    _auto = False
    _order = "pending_count desc, sale_order_id desc"
    _rec_name = "sale_order_id"

    sale_order_id = fields.Many2one("sale.order", string="SE Number", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    user_id = fields.Many2one("res.users", string="Salesperson", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    total_entities = fields.Integer(string="Total Entities", readonly=True)
    listed_count = fields.Integer(string="Listed", readonly=True)
    pending_count = fields.Integer(string="Pending", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT so.id                                AS id,
                       so.id                                AS sale_order_id,
                       so.partner_id                        AS partner_id,
                       so.user_id                           AS user_id,
                       so.company_id                        AS company_id,
                       ent.total                            AS total_entities,
                       COALESCE(lst.listed, 0)              AS listed_count,
                       ent.total - COALESCE(lst.listed, 0)  AS pending_count
                  FROM sale_order so
                  JOIN (SELECT order_id, COUNT(*) AS total
                          FROM sale_order_entity
                         GROUP BY order_id) ent ON ent.order_id = so.id
             LEFT JOIN (SELECT sale_order_id, COUNT(*) AS listed
                          FROM einvoicing_phase1_project
                         GROUP BY sale_order_id) lst ON lst.sale_order_id = so.id
                 WHERE so.approval_state = 'approved'
                   AND so.einvoicing_service IS TRUE
                   AND so.state != 'cancel'
                   AND ent.total > COALESCE(lst.listed, 0)
            )
        """)

    def action_add_project(self):
        """Open a new Phase 1 Project row on this SE."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Phase 1 Project",
            "res_model": "einvoicing.phase1.project",
            "view_mode": "form",
            "target": "current",
            "context": {"default_sale_order_id": self.sale_order_id.id},
        }
