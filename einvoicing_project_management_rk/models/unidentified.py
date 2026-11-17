# -*- coding: utf-8 -*-
from odoo import _, fields, models


class EinvoicingUnidentified(models.Model):
    """Projects whose SE is not yet identified.

    These rows have the same columns as Phase 1 Projects, but the SE is
    optional. Add opens a Phase 1 form pre-filled from the row. When that form
    is saved the row is archived (moved), and its chatter records which
    Phase 1 row it became.
    """
    _name = "einvoicing.unidentified"
    _description = "E-Invoicing Unidentified Project"
    _inherit = ["einvoicing.project.mixin"]
    _order = "s_no, id"
    _rec_name = "name"
    _sequence_code = "einvoicing.unidentified"

    active = fields.Boolean(default=True, tracking=True)
    phase1_project_id = fields.Many2one(
        "einvoicing.phase1.project", string="Added as Phase 1 Project",
        readonly=True, copy=False, index=True)

    def action_add_to_phase1(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Add to Phase 1 Projects"),
            "res_model": "einvoicing.phase1.project",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "current",
            "context": {"epm_from_unidentified_id": self.id},
        }

    def action_open_phase1_project(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "einvoicing.phase1.project",
            "res_id": self.phase1_project_id.id,
            "views": [[False, "form"]],
            "target": "current",
        }
