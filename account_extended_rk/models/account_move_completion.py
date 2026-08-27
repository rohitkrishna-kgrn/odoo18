"""Completion invoice basis check.

Advance, Retainer and Credit Note are self-evident from the document: an
advance is the milestone the plan opens with, a retainer comes off a
retainership contract, a credit note is a reversal. **Completion is the only
classification that is a claim about the state of the engagement** — it says
"the work behind this fee is done and the earlier stages are settled". So it is
the only one the system makes somebody confirm before the invoice posts.

What the check answers, in the order a reviewer would ask it:

1. What is the engagement worth, and on what basis is the plan measured?
2. What is the agreed collection plan — 100% on completion, 50 / 50,
   25 / 25 / 50?
3. How much of it has already been invoiced, and which milestone is next?
4. If the plan opens with an advance, has that advance actually been
   *collected* — not merely raised?
5. Is the delivery work behind a final completion milestone finished?
6. Does the amount on this invoice match what the next milestone calls for?

Anything other than a clean pass is not an error. It is a question put to the
person raising the invoice, who answers it by confirming the basis with a
reason. That reason is stored on the invoice and posted to the chatter.
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError

# Check outcomes that require an explicit human confirmation before the
# completion invoice may be posted.
BLOCKING_STATES = ('over_billed', 'advance_pending', 'work_pending', 'variance')

# Two different questions need two different tolerances.
#
# "Does this invoice amount match the plan?" is a judgement about whether a
# human should be asked to explain a difference, so it is generous: the larger
# of 1% of the expected figure and one unit of currency.
VARIANCE_RATE = 0.01
VARIANCE_FLOOR = 1.0

# "Is this milestone already filled?" is a bookkeeping question, and must stay
# tight. Reusing the generous figure let the 1 AED floor swallow a milestone
# worth 1 AED whole -- the waterfall marked it billed against zero billing and
# reported nothing left to invoice.
FILL_RATE = 0.005


class AccountMove(models.Model):
    _inherit = 'account.move'

    # ------------------------------------------------------------------
    # Which stage of the plan this document bills
    # ------------------------------------------------------------------

    billing_milestone_id = fields.Many2one(
        'sale.order.billing.milestone',
        string='Billing Milestone',
        compute='_compute_billing_position',
        store=True,
        readonly=False,
        copy=False,
        help="Milestone of the engagement's billing plan that this invoice "
             "bills. Matched automatically; correct it by hand if the invoice "
             "belongs to a different stage.",
    )

    billing_stage = fields.Selection(
        [
            ('advance', 'Advance'),
            ('completion', 'Completion'),
        ],
        string='Billing Stage',
        compute='_compute_billing_position',
        store=True,
        copy=False,
        help="Stage of the agreed collection plan this invoice falls in.",
    )

    billing_plan_code = fields.Char(
        string='Payment Plan',
        compute='_compute_billing_position',
        store=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # The check itself
    # ------------------------------------------------------------------

    completion_check_state = fields.Selection(
        [
            ('not_applicable', 'Not Applicable'),
            ('no_plan', 'No Engagement Plan'),
            ('ok', 'Matches Plan'),
            ('variance', 'Amount Differs from Plan'),
            ('advance_pending', 'Advance Not Collected'),
            ('work_pending', 'Work Not Completed'),
            ('over_billed', 'Exceeds Engagement Value'),
        ],
        string='Completion Check',
        compute='_compute_completion_check',
        store=True,
        copy=False,
        help="Result of testing this completion invoice against the "
             "engagement's agreed billing plan.",
    )

    completion_expected_amount = fields.Monetary(
        string='Expected for This Milestone',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
    )
    completion_variance = fields.Monetary(
        string='Variance vs Plan',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
        help="This invoice less what the next unbilled milestone calls for. "
             "Positive means over-billed.",
    )
    completion_prior_invoiced = fields.Monetary(
        string='Already Invoiced',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
        help="Net billed on this engagement before this invoice, credit notes "
             "deducted.",
    )
    completion_balance_amount = fields.Monetary(
        string='Engagement Balance',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
        help="Engagement value still unbilled before this invoice.",
    )
    completion_advance_required = fields.Monetary(
        string='Advance Due',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
    )
    completion_advance_collected = fields.Monetary(
        string='Advance Collected',
        compute='_compute_completion_check', store=True, copy=False,
        currency_field='currency_id',
    )
    completion_work_done = fields.Boolean(
        string='Delivery Complete',
        compute='_compute_completion_check', store=True, copy=False,
        help="Every project delivering this engagement has reached a closing "
             "stage.",
    )

    completion_calculation = fields.Html(
        string='How This Is Calculated',
        compute='_compute_completion_calculation',
        sanitize=False,
        help="Line-by-line working behind the completion check.",
    )

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    completion_confirmed = fields.Boolean(
        string='Completion Basis Confirmed',
        readonly=True, copy=False, tracking=True,
    )
    completion_confirmed_by_id = fields.Many2one(
        'res.users', string='Confirmed By', readonly=True, copy=False)
    completion_confirmed_date = fields.Datetime(
        string='Confirmed On', readonly=True, copy=False)
    completion_confirm_reason = fields.Char(
        string='Confirmation Reason', copy=False, tracking=True,
        help="Why this completion invoice is correct despite differing from "
             "the agreed billing plan.",
    )
    completion_blocked = fields.Boolean(
        string='Awaiting Completion Confirmation',
        compute='_compute_completion_blocked',
        help="True while this completion invoice cannot be posted without a "
             "confirmed basis.",
    )

    # ==================================================================
    # Engagement resolution
    # ==================================================================

    def _completion_engagement_order(self):
        """The sale order whose billing plan governs this invoice.

        The Sale Order Line is the engagement link on every document
        (account_extended_rk 2.2). Retainership invoices and other documents
        stamped only with a project fall back to the project's engagement
        order, which project_extended_rk resolves by SE code.
        """
        self.ensure_one()
        order = self.sale_order_line_id.sudo().order_id
        if order:
            return order
        project = self.service_engagement_id.sudo()
        if not project:
            return self.env['sale.order']
        return project.engagement_order_id or project.sale_order_id

    def _completion_basis_amount(self):
        """This invoice's own amount, measured on the plan's basis."""
        self.ensure_one()
        order = self._completion_engagement_order()
        if order and order.billing_plan_basis == 'total':
            return self.amount_total
        return self.amount_untaxed

    # ==================================================================
    # Milestone matching
    # ==================================================================

    # No dependency on `project.advance_invoice_id`, deliberately. It resolves
    # to the lowest-id invoice on the order, so it never changes once set --
    # raising a second invoice cannot take the title off the first -- and
    # depending on it would wire this compute into a chain that already depends
    # on move.state.
    @api.depends('sale_order_line_id', 'service_engagement_id', 'move_type',
                 'amount_untaxed', 'amount_total', 'retainership_contract_id',
                 'advance_invoice')
    def _compute_billing_position(self):
        """Place each customer invoice on the engagement's billing plan.

        Deliberately does *not* depend on the sibling invoices it reads. A
        stored compute that reacted to every other invoice on the order would
        re-run across the whole engagement on each posting; the position is
        refreshed explicitly at post instead, which is the only moment it
        changes meaningfully.
        """
        # One reverse lookup for the whole batch. Walking forward from the
        # order to its projects misses 28 of them: the Engagement dashboard
        # resolves a project's order by a name regex on the SE code, so the
        # project that names an invoice as its advance is not always reachable
        # through `order_line.project_id`. Asking "which project points at this
        # invoice" cannot miss, and costs one query per recompute batch.
        dashboard_advance_ids = set()
        if self.ids:
            dashboard_advance_ids = set(self.env['project.project'].sudo()
                .with_context(active_test=False)
                .search([('advance_invoice_id', 'in', self.ids)])
                .mapped('advance_invoice_id').ids)

        for move in self:
            # A milestone picked by hand is never overwritten by the matcher.
            manual = move.billing_milestone_id
            move.billing_milestone_id = manual
            move.billing_stage = False
            move.billing_plan_code = False
            if move.move_type != 'out_invoice':
                continue
            order = move._completion_engagement_order()
            move.billing_plan_code = order.billing_plan_code if order else False
            if move.retainership_contract_id:
                continue
            if not order:
                move.billing_stage = 'advance' if move.advance_invoice else False
                continue
            if manual and manual.order_id == order:
                move.billing_stage = ('advance' if move.advance_invoice
                                      else manual.milestone_type)
                continue
            # An invoice the engagement tracker already calls the advance is
            # an advance, full stop -- see _is_engagement_advance_invoice.
            if move._is_engagement_advance_invoice(dashboard_advance_ids):
                move.billing_stage = 'advance'
                move.billing_milestone_id = move._advance_milestone(order)
                continue
            engagement_moves = order.sudo()._billing_plan_customer_moves()
            # The firm's rule, stated plainly: the Completion invoice is the
            # last invoice on the project. Everything raised before it is money
            # taken while the work was still running, which is an Advance.
            move.billing_stage = (
                'completion' if move._is_last_engagement_invoice(engagement_moves)
                else 'advance'
            )
            # The milestone the money lands in is still worked out from the
            # plan -- it is what the amount is checked against -- but it no
            # longer has a say in what the document is called.
            line = move._match_plan_position(order, engagement_moves)['end_line']
            move.billing_milestone_id = line and line.get('milestone') or False

    def _is_last_engagement_invoice(self, engagement_moves):
        """Is this the final invoice raised on the engagement?

        Ordered by invoice date and then id, with an unsaved or undated draft
        sorting last -- it is the newest claim. Credit notes and cancelled
        documents do not compete for the position.

        Note this answer moves. While a project is still being billed, today's
        newest invoice is the Completion; raise another tomorrow and the title
        passes to it, which is correct -- there is only ever one closing invoice
        on an engagement, and it is whichever one turns out to be last.
        """
        self.ensure_one()
        cutoff = self._billing_sort_key()
        for other in engagement_moves:
            if other == self or other.move_type != 'out_invoice':
                continue
            if other.state == 'cancel':
                continue
            if other._billing_sort_key() > cutoff:
                return False
        return True

    def _is_engagement_advance_invoice(self, dashboard_advance_ids=None):
        """Has this invoice already been recognised as the engagement's advance?

        Two existing signals are honoured before the waterfall gets a say, so
        that turning the Invoice Type dropdown into a computed field never takes
        an Advance away from a document that was already being reported as one:

        * `advance_invoice`, the manual tick on the invoice; and
        * `project.advance_invoice_id`, which the Engagement Letter Tracking
          dashboard has been resolving since 2026-08-21 (123 invoices in this
          database) as "the first invoice raised on an order that agreed an
          advance".

        The dashboard's rule and the plan waterfall disagree in one case: an
        invoice that covers the advance *and* more in a single document. The
        dashboard calls it the advance because it came first; the waterfall
        calls it a completion because that is where its last dirham lands.
        Taking the union keeps the dashboard and the AR split view telling the
        same story, which matters more than the edge case.
        """
        self.ensure_one()
        if self.advance_invoice:
            return True
        if dashboard_advance_ids is None:
            dashboard_advance_ids = set(self.env['project.project'].sudo()
                .with_context(active_test=False)
                .search([('advance_invoice_id', '=', self.id)])
                .mapped('advance_invoice_id').ids)
        return self.id in dashboard_advance_ids

    def _advance_milestone(self, order):
        """The plan's advance milestone, when the plan has been materialised."""
        self.ensure_one()
        return order.billing_milestone_ids.filtered(
            lambda milestone: milestone.milestone_type == 'advance')[:1]

    def _match_plan_position(self, order, engagement_moves):
        """Waterfall the engagement's prior billing over the plan.

        Milestones are filled in sequence by everything already invoiced on the
        engagement, and the first one still short is the milestone this invoice
        bills. That is what makes a 25 / 25 / 50 plan work without anyone
        tagging invoices: the third invoice lands on the 50% stage because the
        first two consumed the two 25% stages.

        Returns the target line, what it still needs, the net already invoiced
        and the unbilled balance — all measured on the plan's basis.
        """
        self.ensure_one()
        plan = order._billing_plan_lines()
        prior = self._completion_prior_invoiced(order, engagement_moves)
        remaining = prior
        target, needed = None, 0.0
        for line in plan:
            if remaining >= line['amount'] - self._fill_tolerance(line['amount']):
                remaining -= line['amount']
                continue
            target = line
            needed = line['amount'] - max(remaining, 0.0)
            break
        basis = order._billing_plan_basis_amount()
        return {
            'plan': plan,
            'line': target,
            'end_line': self._plan_end_line(plan, target, needed),
            'needed': needed,
            'prior': prior,
            'balance': max(basis - prior, 0.0),
            'basis': basis,
        }

    def _plan_end_line(self, plan, target, needed):
        """The milestone this invoice's own amount runs out in.

        An invoice does not have to stop at the stage it starts in. Billing
        9,000 against a 50 / 50 plan whose 4,500 advance is unbilled covers the
        advance *and* the completion, and calling the whole document an Advance
        because that is where it began would put a full settlement in the
        dashboard's advance bucket. The stage an invoice is named for is the one
        its last dirham falls in.
        """
        self.ensure_one()
        if not target:
            return None
        amount = self._completion_basis_amount()
        if amount <= needed + self._fill_tolerance(needed):
            return target
        remaining = amount - needed
        end = target
        # Identity, not equality: two milestones of the same name and share are
        # legitimate in a 25 / 25 / 50 plan, and `index()` would find the first.
        after = False
        for line in plan:
            if not after:
                after = line is target
                continue
            end = line
            remaining -= line['amount']
            if remaining <= self._fill_tolerance(line['amount']):
                break
        return end

    def _completion_prior_invoiced(self, order, engagement_moves):
        """Net customer billing raised on this engagement *before* this move.

        Posted invoices and other drafts both count: a draft about to be posted
        has already claimed its share of the plan, and counting it is what stops
        two people drafting the same completion fee. Credit notes are deducted.

        Only documents that come earlier are counted, by invoice date and then
        id. Without that, every historical invoice is measured against invoices
        raised months after it and the whole back catalogue reads as
        over-billed. A draft has no date yet, so it sorts last -- which is
        exactly right: it is the newest claim on the plan.
        """
        self.ensure_one()
        cutoff = self._billing_sort_key()
        total = 0.0
        for other in engagement_moves:
            if other == self or other._billing_sort_key() >= cutoff:
                continue
            amount = (other.amount_total if order.billing_plan_basis == 'total'
                      else other.amount_untaxed)
            total += -amount if other.move_type == 'out_refund' else amount
        return total

    def _billing_sort_key(self):
        """Position of this document in the engagement's billing sequence."""
        self.ensure_one()
        return (
            self.invoice_date or fields.Date.today(),
            self.id if isinstance(self.id, int) else float('inf'),
        )

    def _variance_tolerance(self, expected):
        """Slack allowed between an invoice and the milestone it bills."""
        currency = self.currency_id or self.env.company.currency_id
        return max(abs(expected) * VARIANCE_RATE, VARIANCE_FLOOR, currency.rounding)

    def _fill_tolerance(self, amount):
        """Slack allowed when deciding a milestone has been billed out."""
        currency = self.currency_id or self.env.company.currency_id
        return max(abs(amount) * FILL_RATE, currency.rounding)

    # ==================================================================
    # The completion check
    # ==================================================================

    @api.depends('invoice_type_classification', 'billing_stage', 'billing_milestone_id',
                 'amount_untaxed', 'amount_total', 'state', 'sale_order_line_id',
                 'service_engagement_id')
    def _compute_completion_check(self):
        for move in self:
            move._apply_completion_check(move._evaluate_completion())

    def _apply_completion_check(self, result):
        self.ensure_one()
        self.completion_check_state = result['state']
        self.completion_expected_amount = result['expected']
        self.completion_variance = result['variance']
        self.completion_prior_invoiced = result['prior']
        self.completion_balance_amount = result['balance']
        self.completion_advance_required = result['advance_required']
        self.completion_advance_collected = result['advance_collected']
        self.completion_work_done = result['work_done']

    def _evaluate_completion(self):
        """Run the whole check and return every figure behind it.

        One method produces both the stored verdict and the readable working, so
        the panel on the invoice can never drift from the gate that blocks the
        posting.
        """
        self.ensure_one()
        blank = {
            'state': 'not_applicable', 'expected': 0.0, 'variance': 0.0,
            'prior': 0.0, 'balance': 0.0, 'advance_required': 0.0,
            'advance_collected': 0.0, 'work_done': False, 'order': False,
            'plan': [], 'line': None, 'amount': 0.0, 'basis': 0.0,
            'advance_outstanding': 0.0, 'projects': self.env['project.project'],
        }
        if self.move_type != 'out_invoice' or self.invoice_type_classification != 'completion':
            return blank

        order = self._completion_engagement_order()
        if not order or order._billing_plan_basis_amount() <= 0.0:
            return dict(blank, state='no_plan', order=order)

        # Fetched once and threaded through: the position waterfall and the
        # advance test read the same set of invoices, and re-searching per
        # question turns a recompute over the whole ledger into three.
        engagement_moves = order.sudo()._billing_plan_customer_moves()
        position = self._match_plan_position(order, engagement_moves)
        amount = self._completion_basis_amount()
        expected = position['needed']
        advance_required, advance_collected = self._advance_position(
            order, position['plan'], engagement_moves)
        advance_outstanding = advance_required - advance_collected
        projects = order.sudo().order_line.project_id
        work_done = bool(projects) and all(
            project.stage_id.fold or project.completed_date for project in projects
        )

        result = dict(
            blank,
            expected=expected,
            variance=amount - expected,
            prior=position['prior'],
            balance=position['balance'],
            advance_required=advance_required,
            advance_collected=advance_collected,
            advance_outstanding=advance_outstanding,
            work_done=work_done,
            order=order,
            plan=position['plan'],
            line=position['line'],
            amount=amount,
            basis=position['basis'],
            projects=projects,
        )

        # Precedence runs from "this cannot be right" down to "this needs a
        # second look": billing past the engagement value is the hardest
        # failure, a plan-matching amount the softest pass.
        tolerance = self._variance_tolerance(expected or position['balance'])
        if amount > position['balance'] + tolerance:
            result['state'] = 'over_billed'
        elif advance_outstanding > self._variance_tolerance(advance_required):
            result['state'] = 'advance_pending'
        elif not work_done:
            result['state'] = 'work_pending'
        elif abs(amount - expected) > tolerance:
            result['state'] = 'variance'
        else:
            result['state'] = 'ok'
        return result

    def _advance_position(self, order, plan, engagement_moves):
        """What the plan asks for up front, and what has actually been banked.

        Both figures are in cash terms — money received is always VAT-inclusive,
        so a plan measured on the untaxed amount is grossed up before the
        comparison rather than comparing a net requirement against a gross
        receipt.
        """
        self.ensure_one()
        required = sum(line['amount'] for line in plan if line['type'] == 'advance')
        if not required:
            return 0.0, 0.0
        required *= order._billing_gross_factor()
        collected = 0.0
        for move in engagement_moves:
            if move.move_type != 'out_invoice' or move.state != 'posted':
                continue
            # billing_stage rather than invoice_type_classification: the stage
            # is what the classification is derived from, and reading it here
            # keeps this off its own compute chain.
            if move.billing_stage != 'advance' and not move.advance_invoice:
                continue
            collected += move.amount_total - move.amount_residual
        return required, collected

    # ==================================================================
    # Readable working
    # ==================================================================

    def _compute_completion_calculation(self):
        for move in self:
            move.completion_calculation = move._render_completion_calculation()

    def _render_completion_calculation(self):
        self.ensure_one()
        result = self._evaluate_completion()
        if result['state'] == 'not_applicable':
            return False

        currency = self.currency_id or self.env.company.currency_id
        def money(amount):
            return '%s&nbsp;%s' % (currency.symbol or currency.name,
                                   '{:,.2f}'.format(amount or 0.0))

        order = result['order']
        if result['state'] == 'no_plan':
            return (
                '<div class="alert alert-warning mb-0">This invoice is not linked '
                'to a priced engagement, so there is no billing plan to check it '
                'against. Set the Sale Order Line.</div>'
            )

        basis_label = (_('Total incl. Tax') if order.billing_plan_basis == 'total'
                       else _('Untaxed Amount'))
        rows = []

        # 1. The engagement and its plan
        rows.append(
            '<tr><td colspan="4" class="fw-bold bg-light">1. Engagement &amp; agreed plan</td></tr>')
        rows.append(
            '<tr><td>Engagement</td><td colspan="3">%s &mdash; %s</td></tr>'
            % (order.name, order.partner_id.display_name))
        rows.append(
            '<tr><td>Engagement value (%s)</td><td colspan="3">%s</td></tr>'
            % (basis_label, money(result['basis'])))
        rows.append(
            '<tr><td>Payment plan</td><td colspan="3">%s%s</td></tr>'
            % (order.billing_plan_code or _('none'),
               _(' (derived from the advance on the order)')
               if order.billing_plan_is_derived else _(' (entered on the order)')))

        # 2. The plan, milestone by milestone, and where the prior billing sat
        rows.append(
            '<tr><td colspan="4" class="fw-bold bg-light">2. Plan milestones vs billing to date</td></tr>')
        rows.append('<tr class="text-muted"><td>Milestone</td><td class="text-end">Share</td>'
                    '<td class="text-end">Planned</td><td>Status</td></tr>')
        consumed = result['prior']
        for line in result['plan']:
            covered = min(max(consumed, 0.0), line['amount'])
            consumed -= line['amount']
            if line is result['line']:
                status = _('<strong>this invoice</strong> &mdash; %s of %s outstanding') % (
                    money(result['expected']), money(line['amount']))
            elif covered >= line['amount'] - self._fill_tolerance(line['amount']):
                status = _('billed (%s)') % money(covered)
            elif covered > 0:
                status = _('part billed (%s)') % money(covered)
            else:
                status = _('not yet billed')
            rows.append(
                '<tr><td>%s</td><td class="text-end">%.2f%%</td>'
                '<td class="text-end">%s</td><td>%s</td></tr>'
                % (line['name'], line['percentage'], money(line['amount']), status))
        rows.append(
            '<tr><td>Already invoiced on this engagement</td><td colspan="2" class="text-end">%s</td>'
            '<td>net of credit notes, this invoice excluded</td></tr>' % money(result['prior']))
        rows.append(
            '<tr><td>Unbilled balance</td><td colspan="2" class="text-end">%s</td>'
            '<td>%s &minus; %s</td></tr>'
            % (money(result['balance']), money(result['basis']), money(result['prior'])))

        # 3. Advance
        rows.append(
            '<tr><td colspan="4" class="fw-bold bg-light">3. Advance position</td></tr>')
        if not result['advance_required']:
            rows.append('<tr><td colspan="4">The plan asks for no advance.</td></tr>')
        else:
            rows.append('<tr><td>Advance the plan calls for</td><td colspan="2" class="text-end">%s</td>'
                        '<td>gross of tax</td></tr>' % money(result['advance_required']))
            rows.append('<tr><td>Advance actually collected</td><td colspan="2" class="text-end">%s</td>'
                        '<td>posted advance invoices, less amount still due</td></tr>'
                        % money(result['advance_collected']))
            rows.append('<tr><td>Advance outstanding</td><td colspan="2" class="text-end">%s</td>'
                        '<td>%s</td></tr>'
                        % (money(result['advance_outstanding']),
                           _('cleared') if result['advance_outstanding'] <= 0
                           else _('<strong>not yet collected</strong>')))

        # 4. Delivery
        rows.append(
            '<tr><td colspan="4" class="fw-bold bg-light">4. Delivery status</td></tr>')
        if not result['projects']:
            rows.append('<tr><td colspan="4">No project is linked to this engagement, '
                        'so delivery could not be checked.</td></tr>')
        else:
            for project in result['projects']:
                rows.append('<tr><td>%s</td><td colspan="3">%s</td></tr>' % (
                    project.display_name,
                    _('complete (%s)') % project.stage_id.display_name
                    if project.stage_id.fold or project.completed_date
                    else _('<strong>in progress</strong> (%s)') % project.stage_id.display_name))

        # 5. Verdict
        rows.append(
            '<tr><td colspan="4" class="fw-bold bg-light">5. This invoice</td></tr>')
        rows.append('<tr><td>Invoice amount (%s)</td><td colspan="2" class="text-end">%s</td>'
                    '<td></td></tr>' % (basis_label, money(result['amount'])))
        rows.append('<tr><td>Expected for the next milestone</td><td colspan="2" class="text-end">%s</td>'
                    '<td></td></tr>' % money(result['expected']))
        rows.append('<tr><td class="fw-bold">Variance</td><td colspan="2" class="text-end fw-bold">%s</td>'
                    '<td>invoice &minus; expected</td></tr>' % money(result['variance']))

        verdicts = {
            'ok': ('success', _('Matches the agreed plan. No confirmation needed.')),
            'variance': ('warning', _(
                'This invoice differs from the next milestone by %s. Confirm the '
                'basis with a reason if the amount is right.') % money(result['variance'])),
            'advance_pending': ('danger', _(
                'The plan opens with an advance of %s and only %s has been '
                'collected. Collect the advance, or confirm the basis with a '
                'reason.') % (money(result['advance_required']),
                              money(result['advance_collected']))),
            'work_pending': ('warning', _(
                'This bills the final completion milestone, but the delivery '
                'project has not reached a closing stage.')),
            'over_billed': ('danger', _(
                'This invoice takes total billing past the engagement value: '
                'only %s is unbilled.') % money(result['balance'])),
        }
        level, message = verdicts.get(result['state'], ('secondary', ''))
        return (
            '<table class="table table-sm mb-2"><tbody>%s</tbody></table>'
            '<div class="alert alert-%s mb-0">%s</div>'
        ) % (''.join(rows), level, message)

    # ==================================================================
    # The posting gate
    # ==================================================================

    @api.depends('completion_check_state', 'completion_confirmed', 'state')
    def _compute_completion_blocked(self):
        for move in self:
            move.completion_blocked = bool(
                move.state == 'draft'
                and move.completion_check_state in BLOCKING_STATES
                and not move.completion_confirmed
            )

    def action_confirm_completion_basis(self):
        """Record that the person raising the invoice stands behind the amount."""
        for move in self:
            if move.completion_check_state not in BLOCKING_STATES:
                continue
            if not move.completion_confirm_reason:
                raise UserError(_(
                    "Enter a Confirmation Reason before confirming the completion "
                    "basis of %s. The billing plan says %s and this invoice is "
                    "for a different amount, so the file needs to say why."
                ) % (move.display_name, move.completion_plan_summary()))
            move.write({
                'completion_confirmed': True,
                'completion_confirmed_by_id': self.env.user.id,
                'completion_confirmed_date': fields.Datetime.now(),
            })
            move.message_post(body=_(
                "Completion basis confirmed by %s. Check result: %s. Reason: %s"
            ) % (self.env.user.display_name,
                 dict(self._fields['completion_check_state'].selection).get(
                     move.completion_check_state),
                 move.completion_confirm_reason))
        return True

    def completion_plan_summary(self):
        self.ensure_one()
        order = self._completion_engagement_order()
        return _('%s on %s') % (order.billing_plan_code or _('no plan'),
                                order.name or _('no engagement'))

    def write(self, vals):
        """A confirmed basis is a confirmation of an amount, not of an invoice.

        Change what is billed and the confirmation lapses, so nobody can confirm
        a compliant figure and then edit the lines.
        """
        res = super().write(vals)
        if 'invoice_line_ids' in vals or 'sale_order_line_id' in vals:
            stale = self.filtered(
                lambda move: move.completion_confirmed and move.state == 'draft')
            if stale:
                super(AccountMove, stale).write({
                    'completion_confirmed': False,
                    'completion_confirmed_by_id': False,
                    'completion_confirmed_date': False,
                })
        return res

    def _post(self, soft=True):
        blocked = self.filtered('completion_blocked')
        if blocked:
            raise UserError(_(
                "These completion invoices have not had their billing basis "
                "confirmed:\n\n%s\n\nOpen the invoice, check the working in "
                "the banner at the top, enter a Confirmation Reason and press "
                "Confirm Completion Basis."
            ) % '\n'.join(
                ' • %s — %s' % (
                    move.display_name,
                    dict(self._fields['completion_check_state'].selection).get(
                        move.completion_check_state))
                for move in blocked))
        res = super()._post(soft=soft)
        # Posting changes what every other invoice on the engagement is
        # measured against, so refresh the whole engagement's positions now
        # rather than making the stored compute depend on its own siblings.
        self._refresh_engagement_billing_position()
        return res

    def _refresh_engagement_billing_position(self):
        siblings = self.browse()
        for move in self:
            order = move._completion_engagement_order()
            if order:
                siblings |= order.sudo()._billing_plan_customer_moves()
        siblings = siblings.filtered(lambda m: m.state == 'draft') - self
        if siblings:
            siblings.modified(['amount_untaxed', 'amount_total'])


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @staticmethod
    def _lapse_completion_confirmation(moves):
        """Drop the confirmed basis on invoices whose amount has moved.

        `AccountMove.write` catches the web client, which edits lines by sending
        an `invoice_line_ids` command list on the move. Anything that writes a
        line directly -- a script, an import, a server action -- never touches
        the move's vals, and without this a confirmed invoice could be re-priced
        with the confirmation still standing.
        """
        stale = moves.filtered(
            lambda move: move.completion_confirmed and move.state == 'draft')
        if stale:
            stale.write({
                'completion_confirmed': False,
                'completion_confirmed_by_id': False,
                'completion_confirmed_date': False,
            })

    # Amount-bearing fields only: a note or an analytic tag changes nothing the
    # billing plan is measured against.
    _COMPLETION_AMOUNT_FIELDS = frozenset({
        'price_unit', 'quantity', 'discount', 'tax_ids', 'product_id',
        'sale_line_ids', 'currency_id',
    })

    def write(self, vals):
        res = super().write(vals)
        if self._COMPLETION_AMOUNT_FIELDS.intersection(vals):
            self._lapse_completion_confirmation(self.mapped('move_id'))
        return res

    def unlink(self):
        # Captured before the delete: afterwards the lines are gone and there
        # is nothing left to walk back up to the invoice.
        moves = self.mapped('move_id')
        res = super().unlink()
        self._lapse_completion_confirmation(moves.exists())
        return res
