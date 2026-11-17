# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

YES_NO = [("yes", "Yes"), ("no", "No")]


class EinvoicingProjectMixin(models.AbstractModel):
    """The columns Phase 1 Projects and Unidentified share.

    Each concrete model names its own S.No sequence in ``_sequence_code``.
    Phase 1 makes the SE required; on Unidentified it is optional.
    """
    _name = "einvoicing.project.mixin"
    _description = "E-Invoicing Project Columns"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _sequence_code = False

    s_no = fields.Integer(
        string="S.No", readonly=True, copy=False, tracking=True,
        help="Assigned automatically, in the order rows are created.")
    name = fields.Char(string="Emaratax Legal Name", required=True, tracking=True)
    peppol_id = fields.Char(string="Peppol ID", tracking=True)
    sale_order_id = fields.Many2one(
        "sale.order", string="SE Number", index=True,
        tracking=True, ondelete="restrict",
        domain="[('approval_state', '=', 'approved'), ('einvoicing_service', '=', True), ('state', '!=', 'cancel')]")
    partner_id = fields.Many2one(
        related="sale_order_id.partner_id", string="Customer", store=True)
    company_id = fields.Many2one(
        related="sale_order_id.company_id", string="Company", store=True)
    user_id = fields.Many2one(
        related="sale_order_id.user_id", string="Salesperson", store=True)
    # Filled from the SE's order lines when the SE is picked, then editable per
    # row. Renewal = the day after the last engagement end, the same rule the
    # SE billing view used.
    subscription_start_date = fields.Date(
        string="Subscription Start Date", compute="_compute_subscription_start_date",
        store=True, readonly=False, tracking=True,
        help="Taken from the earliest Engagement Start on the SE's order lines "
             "when the SE is chosen. Can be changed per row.")
    renewal_date = fields.Date(
        string="Renewal Date", compute="_compute_renewal_date",
        store=True, readonly=False, tracking=True,
        help="The day after the latest Engagement End on the SE's order lines, "
             "filled when the SE is chosen. Can be changed per row.")
    gap_assessment = fields.Selection([
        ("new", "New"),
        ("in_progress", "In Progress"),
        ("on_hold", "On Hold"),
        ("done", "Done"),
        ("cancelled", "Cancelled"),
    ], string="Gap Assessment", default="new", required=True, tracking=True)
    uat_onboarding = fields.Selection(
        YES_NO, string="UAT Onboarding", default="no", required=True, tracking=True)
    emaratax_onboarding = fields.Selection([
        ("active", "Active"),
        ("suspended", "Suspended"),
        ("delinked", "Delinked"),
    ], string="Emaratax Onboarding", tracking=True)
    live_middleware = fields.Selection(
        YES_NO, string="LIVE Middleware", default="no", required=True, tracking=True)
    remarks = fields.Char(string="Remarks - Emaratax", tracking=True)

    # Two computes, not one shared: on create Odoo protects every field of a
    # shared compute as soon as ONE of them is in vals, so typing only the
    # Renewal Date would leave the start date blank.
    def _se_lines(self):
        # sudo: a User may not be allowed to read another salesperson's order
        # lines, but the SE itself is already chosen on the row.
        return self.sale_order_id.sudo().order_line.filtered(lambda l: not l.display_type)

    @api.depends("sale_order_id")
    def _compute_subscription_start_date(self):
        for rec in self:
            starts = [d for d in rec._se_lines().mapped("engagement_start") if d]
            rec.subscription_start_date = min(starts) if starts else False

    @api.depends("sale_order_id")
    def _compute_renewal_date(self):
        for rec in self:
            ends = [d for d in rec._se_lines().mapped("engagement_end") if d]
            rec.renewal_date = (max(ends) + timedelta(days=1)) if ends else False

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if not vals.get("s_no"):
                vals["s_no"] = int(sequence.next_by_code(self._sequence_code))
        return super().create(vals_list)
