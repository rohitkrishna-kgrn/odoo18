from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = 'account.move'

    why_not_collected = fields.Text(
        string='Why Not Collected',
        tracking=True,
        help="Reason the AR owner (Project Manager) has not yet collected this "
             "invoice. Prompted for on the invoice form once it's more than 30 "
             "days overdue, and re-prompted once the reason on file is 7+ days "
             "old. The Monday report flags it as 'AR Responsible: Not "
             "Mentioned' until this is set.",
    )

    why_not_collected_date = fields.Date(
        string='Why Not Collected — Last Updated',
        help="Date the current reason was last recorded. Stamped automatically "
             "whenever Why Not Collected is changed.",
    )

    why_not_collected_needs_prompt = fields.Boolean(
        string='Needs Why-Not-Collected Prompt',
        compute='_compute_why_not_collected_needs_prompt',
        help="True when this invoice is >30 days overdue, not excluded from "
             "the report, and either has no reason yet or its reason is 7+ "
             "days old — used to decide whether to pop the reason dialog.",
    )

    overdue_report_excluded = fields.Boolean(
        string='Excluded From Overdue Report',
        tracking=True,
        help="When set, this invoice is left out of the Monday overdue "
             "report (both the recipient-group and per-PM emails) and no "
             "longer prompts for a 'Why Not Collected' reason. Set/unset via "
             "Exclude Invoice / Include Invoice in the AR Aging Dashboard's "
             "Actions menu.",
    )

    overdue_report_inclusion = fields.Selection(
        [
            ('included', 'Included Invoices'),
            ('excluded', 'Excluded Invoices'),
        ],
        string='Report Inclusion',
        compute='_compute_overdue_report_inclusion', store=True,
        help="Top-level split for the AR Aging Dashboard: Included Invoices "
             "vs. Excluded Invoices, each then sub-grouped by Aging Bucket "
             "(days) underneath.",
    )

    @api.depends('invoice_age_days', 'why_not_collected', 'why_not_collected_date', 'overdue_report_excluded')
    def _compute_why_not_collected_needs_prompt(self):
        today = fields.Date.context_today(self)
        for move in self:
            if move.invoice_age_days <= 30 or move.overdue_report_excluded:
                move.why_not_collected_needs_prompt = False
            elif not move.why_not_collected or not move.why_not_collected_date:
                move.why_not_collected_needs_prompt = True
            else:
                move.why_not_collected_needs_prompt = \
                    (today - move.why_not_collected_date).days >= 7

    @api.depends('overdue_report_excluded')
    def _compute_overdue_report_inclusion(self):
        for move in self:
            move.overdue_report_inclusion = 'excluded' if move.overdue_report_excluded else 'included'

    def write(self, vals):
        if vals.get('why_not_collected') and 'why_not_collected_date' not in vals:
            vals = dict(vals, why_not_collected_date=fields.Date.context_today(self))
        return super().write(vals)
