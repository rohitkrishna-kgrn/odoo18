"""Engagement billing plan — how the firm agreed to collect the fee.

A completion invoice cannot be judged on its own. "Is AED 5,000 the right
amount to bill now?" only has an answer once you know the engagement is worth
AED 10,000, that the plan is 50 / 50, and that the 50% advance has already been
collected. This module holds that plan.

Two things make the plan usable on day one rather than a form nobody fills in:

* **The plan is virtual until someone edits it.** Every confirmed order already
  carries `advance_amount`; `_billing_plan_lines()` turns that into a plan on
  the fly (advance + completion, or a single 100% completion line when there is
  no advance). No backfill, no data entry, and the completion check works on all
  3,301 confirmed orders immediately. Clicking *Set Up Billing Plan* on the
  order materialises the same lines as records so finance can change them.

* **The basis is chosen, not assumed.** In this database `advance_amount` is
  sometimes half the untaxed amount (69 orders read as 50% of untaxed) and
  sometimes half the VAT-inclusive total (32 orders read as 53% of untaxed,
  which is 50% of the total). Comparing against the wrong one turns a correct
  invoice into a variance. `billing_plan_basis` is computed per order by trying
  both and keeping whichever lands closest to a percentage a human would
  actually contract on.
"""
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Percentages the firm actually writes into engagement letters. A derived
# percentage snaps to one of these when it is within SNAP_TOLERANCE points, so
# a 50% advance taken on the untaxed amount of a VAT-bearing order reads as
# "50 / 50" instead of "47.62 / 52.38". Snapping only ever changes the label —
# the money on the milestone stays exactly the advance that was agreed.
NICE_PERCENTAGES = (
    10.0, 15.0, 20.0, 25.0, 30.0, 100.0 / 3.0, 40.0, 50.0,
    60.0, 200.0 / 3.0, 70.0, 75.0, 80.0, 90.0, 100.0,
)
SNAP_TOLERANCE = 3.0

# Only the two stages the firm's Invoice Type dropdown knows about. There is
# deliberately no Progress / Interim or Retention type: a 25 / 25 / 50 plan is
# an Advance followed by two Completion milestones, and whether delivery has to
# be finished is decided by a milestone's *position* in the plan -- the last one
# is the real completion -- not by a label. Anything else would invent a fifth
# invoice type the dashboard cannot show.
MILESTONE_TYPES = [
    ('advance', 'Advance'),
    ('completion', 'Completion'),
]


def _snap_percentage(pct):
    """Round `pct` to the nearest contracted percentage if it is close enough."""
    if pct <= 0.0:
        return 0.0
    nearest = min(NICE_PERCENTAGES, key=lambda nice: abs(nice - pct))
    return nearest if abs(nearest - pct) <= SNAP_TOLERANCE else round(pct, 2)


class SaleOrderBillingMilestone(models.Model):
    _name = 'sale.order.billing.milestone'
    _description = 'Engagement Billing Milestone'
    _order = 'order_id, sequence, id'

    order_id = fields.Many2one(
        'sale.order',
        string='Engagement',
        required=True,
        ondelete='cascade',
        index=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Milestone', required=True)
    milestone_type = fields.Selection(
        MILESTONE_TYPES,
        string='Type',
        required=True,
        default='completion',
        help="Advance is collected before work starts. Everything billed after "
             "that is a Completion stage; the last one in the plan is the one "
             "that requires delivery to be finished.",
    )
    percentage = fields.Float(
        string='Percentage',
        digits=(5, 2),
        required=True,
        help="Share of the engagement value billed at this milestone.",
    )
    trigger = fields.Selection(
        [
            ('on_confirmation', 'On Order Confirmation'),
            ('on_project_stage', 'When Project Reaches Stage'),
            ('on_completion', 'On Engagement Completion'),
            ('manual', 'Manual / As Agreed'),
        ],
        string='Billed When',
        required=True,
        default='manual',
    )
    trigger_stage_id = fields.Many2one(
        'project.project.stage',
        string='Trigger Stage',
        help="Project stage that makes this milestone billable.",
    )

    currency_id = fields.Many2one(related='order_id.currency_id', readonly=True)

    # Stored compute with readonly=False: normally percentage x basis, but the
    # derived advance line writes the exact agreed advance so the snapped label
    # never moves the money, and finance can pin an odd figure by hand.
    planned_amount = fields.Monetary(
        string='Planned Amount',
        compute='_compute_planned_amount',
        store=True,
        readonly=False,
        currency_field='currency_id',
    )

    invoiced_amount = fields.Monetary(
        string='Invoiced',
        compute='_compute_billed_amounts',
        currency_field='currency_id',
    )
    collected_amount = fields.Monetary(
        string='Collected',
        compute='_compute_billed_amounts',
        currency_field='currency_id',
    )
    state = fields.Selection(
        [
            ('pending', 'Not Billed'),
            ('partial', 'Partly Billed'),
            ('invoiced', 'Invoiced'),
            ('paid', 'Collected'),
        ],
        string='Status',
        compute='_compute_billed_amounts',
    )

    @api.depends('percentage', 'order_id.amount_untaxed', 'order_id.amount_total',
                 'order_id.billing_plan_basis')
    def _compute_planned_amount(self):
        for milestone in self:
            order = milestone.order_id
            basis = order._billing_plan_basis_amount() if order else 0.0
            milestone.planned_amount = basis * (milestone.percentage or 0.0) / 100.0

    @api.depends('planned_amount')
    def _compute_billed_amounts(self):
        """Read the invoices matched to each milestone.

        `sudo()` because the sale order form is opened by PMs and sales users
        who have no read access to `account.move` in this database — without it
        the o2m would raise rather than simply show zeros.
        """
        grouped = {}
        if self.ids:
            grouped = {
                milestone.id: (invoiced, collected)
                for milestone, invoiced, collected in self.env['account.move'].sudo()._read_group(
                    [('billing_milestone_id', 'in', self.ids),
                     ('move_type', '=', 'out_invoice'),
                     ('state', '=', 'posted')],
                    groupby=['billing_milestone_id'],
                    aggregates=['amount_total:sum', 'amount_residual:sum'],
                )
            }
        for milestone in self:
            invoiced, residual = grouped.get(milestone.id, (0.0, 0.0))
            milestone.invoiced_amount = invoiced
            milestone.collected_amount = invoiced - residual
            currency = milestone.currency_id or self.env.company.currency_id
            planned = milestone.planned_amount
            if currency.is_zero(invoiced):
                milestone.state = 'pending'
            elif currency.compare_amounts(milestone.collected_amount, planned) >= 0:
                milestone.state = 'paid'
            elif currency.compare_amounts(invoiced, planned) >= 0:
                milestone.state = 'invoiced'
            else:
                milestone.state = 'partial'

    @api.constrains('percentage')
    def _check_percentage(self):
        for milestone in self:
            if milestone.percentage <= 0.0 or milestone.percentage > 100.0:
                raise ValidationError(_(
                    "Milestone '%s': the percentage must be greater than 0 and "
                    "at most 100.") % milestone.name)

    @api.constrains('percentage', 'order_id')
    def _check_plan_totals_100(self):
        for order in self.mapped('order_id'):
            total = sum(order.billing_milestone_ids.mapped('percentage'))
            # Two decimals of tolerance so 33.33 / 33.33 / 33.34 is accepted.
            if abs(total - 100.0) > 0.05:
                raise ValidationError(_(
                    "The billing plan on %s adds up to %.2f%%. A billing plan "
                    "must account for exactly 100%% of the engagement value."
                ) % (order.name, total))


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    billing_milestone_ids = fields.One2many(
        'sale.order.billing.milestone',
        'order_id',
        string='Billing Plan',
        copy=True,
    )

    billing_plan_basis = fields.Selection(
        [
            ('untaxed', 'Untaxed Amount'),
            ('total', 'Total incl. Tax'),
        ],
        string='Plan Basis',
        compute='_compute_billing_plan_basis',
        store=True,
        readonly=False,
        default='untaxed',
        help="Amount the milestone percentages are taken on. Detected from the "
             "advance already agreed; override it if the engagement letter says "
             "otherwise.",
    )

    billing_plan_code = fields.Char(
        string='Payment Plan',
        compute='_compute_billing_plan_code',
        store=True,
        help="Short form of the agreed collection plan, e.g. 50 / 50 or "
             "25 / 25 / 50.",
    )

    billing_plan_is_derived = fields.Boolean(
        string='Plan Derived',
        compute='_compute_billing_plan_code',
        store=True,
        help="True while the plan is inferred from the advance amount rather "
             "than entered on the order.",
    )

    # ------------------------------------------------------------------
    # Basis and plan derivation
    # ------------------------------------------------------------------

    @api.depends('advance_amount', 'amount_untaxed', 'amount_total')
    def _compute_billing_plan_basis(self):
        """Pick the basis the advance was actually calculated on.

        An advance of 5,000 on an order of 10,000 + 500 VAT is 50% of the
        untaxed amount and 47.62% of the total; an advance of 5,250 is 52.5% of
        untaxed and 50% of the total. Whichever reading lands closer to a
        percentage a human would contract on is the one that was meant.
        """
        for order in self:
            untaxed, total = order.amount_untaxed, order.amount_total
            advance = order.advance_amount or 0.0
            if advance <= 0.0 or untaxed <= 0.0 or total <= 0.0:
                order.billing_plan_basis = 'untaxed'
                continue
            distances = {}
            for basis, amount in (('untaxed', untaxed), ('total', total)):
                pct = advance / amount * 100.0
                # An advance that exceeds the basis is not a reading of it.
                distances[basis] = (
                    abs(_snap_percentage(pct) - pct) if pct <= 100.5 else 1e6
                )
            order.billing_plan_basis = min(distances, key=distances.get)

    def _billing_plan_basis_amount(self):
        """Engagement value the milestone percentages apply to."""
        self.ensure_one()
        return self.amount_total if self.billing_plan_basis == 'total' else self.amount_untaxed

    def _billing_gross_factor(self):
        """Multiplier from a basis amount to the cash the client actually pays.

        1.0 when the plan is already on the tax-inclusive total; the tax ratio
        of the order otherwise. Used to compare a planned share against money
        received, which is always VAT-inclusive.
        """
        self.ensure_one()
        if self.billing_plan_basis == 'total' or not self.amount_untaxed:
            return 1.0
        return (self.amount_total or self.amount_untaxed) / self.amount_untaxed

    def _billing_plan_lines(self):
        """The engagement's billing plan, whether or not it was ever entered.

        Returns an ordered list of dicts — `milestone` holds the record when the
        plan has been materialised and False when it is derived on the fly, so
        one caller handles both.
        """
        self.ensure_one()
        if self.billing_milestone_ids:
            return [{
                'milestone': milestone,
                'name': milestone.name,
                'type': milestone.milestone_type,
                'percentage': milestone.percentage,
                'amount': milestone.planned_amount,
            } for milestone in self.billing_milestone_ids]
        return [dict(vals, milestone=False) for vals in self._derived_billing_plan()]

    def _derived_billing_plan(self):
        """Infer the plan from the advance recorded on the order."""
        self.ensure_one()
        basis = self._billing_plan_basis_amount()
        advance = self.advance_amount or 0.0
        if basis <= 0.0:
            return []
        if advance <= 0.0:
            return [{
                'name': _('Completion'), 'type': 'completion',
                'percentage': 100.0, 'amount': basis,
            }]
        # An advance at or above the basis is a full payment up front, not an
        # advance with an empty completion stage behind it.
        rounding = (self.currency_id or self.env.company.currency_id).rounding
        if advance >= basis - rounding:
            return [{
                'name': _('Full Payment in Advance'), 'type': 'advance',
                'percentage': 100.0, 'amount': basis,
            }]
        advance_pct = _snap_percentage(advance / basis * 100.0)
        return [
            {'name': _('Advance'), 'type': 'advance',
             'percentage': advance_pct, 'amount': advance},
            {'name': _('Completion'), 'type': 'completion',
             'percentage': round(100.0 - advance_pct, 2), 'amount': basis - advance},
        ]

    @api.depends('billing_milestone_ids.percentage', 'billing_milestone_ids.sequence',
                 'advance_amount', 'amount_untaxed', 'amount_total', 'billing_plan_basis')
    def _compute_billing_plan_code(self):
        for order in self:
            order.billing_plan_is_derived = not order.billing_milestone_ids
            lines = order._billing_plan_lines()
            if not lines:
                order.billing_plan_code = False
            elif len(lines) == 1 and lines[0]['type'] == 'advance':
                order.billing_plan_code = _('100% Advance')
            elif len(lines) == 1:
                order.billing_plan_code = _('100% on Completion')
            else:
                order.billing_plan_code = ' / '.join(
                    ('%g' % round(line['percentage'], 2)) for line in lines
                )

    def action_setup_billing_plan(self):
        """Materialise the derived plan so it can be edited on the order."""
        for order in self:
            if order.billing_milestone_ids:
                continue
            order.billing_milestone_ids = [
                (0, 0, {
                    'sequence': (index + 1) * 10,
                    'name': line['name'],
                    'milestone_type': line['type'],
                    'percentage': line['percentage'],
                    'planned_amount': line['amount'],
                    'trigger': ('on_confirmation' if line['type'] == 'advance'
                                else 'on_completion'),
                })
                for index, line in enumerate(order._derived_billing_plan())
            ]
        return True

    def action_reset_billing_plan(self):
        """Drop the entered plan and fall back to the derived one."""
        self.mapped('billing_milestone_ids').unlink()
        return True

    def _billing_plan_customer_moves(self):
        """Every customer invoice and credit note raised against this engagement.

        Invoices reach an order through `sale_order_line_id`, which
        account_extended_rk 2.2 made the single engagement link, but retainer
        invoices and hand-made documents carry only the project. Both routes are
        unioned so the plan is measured against everything actually billed, and
        cancelled documents are dropped because they claim nothing.
        """
        self.ensure_one()
        Move = self.env['account.move'].sudo()
        moves = Move.search([
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '!=', 'cancel'),
            ('sale_order_line_id', 'in', self.order_line.ids),
        ])
        projects = self.order_line.project_id
        if projects:
            moves |= Move.search([
                ('move_type', 'in', ('out_invoice', 'out_refund')),
                ('state', '!=', 'cancel'),
                ('service_engagement_id', 'in', projects.ids),
            ])
        return moves
