import calendar
import logging

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, Command
from odoo.exceptions import UserError, ValidationError

from .product_template import (
    RETAINERSHIP_INTERVALS,
    RETAINERSHIP_INTERVAL_MONTHS,
    MAX_BILLING_DAY,
)

_logger = logging.getLogger(__name__)

# Summary used on the review activity raised against every generated draft.
# Matched by name when the invoice is posted so only this activity is closed
# and unrelated to-dos on the invoice are left alone.
REVIEW_ACTIVITY_SUMMARY = 'Review retainership draft invoice'

# Safety rail on catch-up: a contract whose schedule is far in the past (data
# import, long pause, cron switched off) generates at most this many drafts in
# one run, so nobody wakes up to three years of invoices in one go.
MAX_CATCHUP_PERIODS = 12


class RetainershipContract(models.Model):
    _name = 'retainership.contract'
    _description = 'Retainership Billing Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'next_invoice_date, id'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
    )
    active = fields.Boolean(default=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        required=True,
        tracking=True,
        help="Client the retainer is billed to.",
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        tracking=True,
        domain="[('order_partner_id', '=', partner_id)]",
        help="Sale order line every generated invoice is billed against. The "
             "engagement is taken from the project this line delivers.",
    )
    # Kept, but no longer picked by hand -- it follows the Sale Order Line, and
    # is what carries the three legacy contracts whose project never had a sale
    # order line to point at.
    service_engagement_id = fields.Many2one(
        'project.project',
        string='Service Engagement',
        tracking=True,
        readonly=True,
        help="Project the Sale Order Line delivers. Every generated invoice is "
             "billed against it.",
    )
    ar_responsible_id = fields.Many2one(
        'res.users',
        string='AR Responsible',
        required=True,
        domain=[('share', '=', False)],
        tracking=True,
        help="Carried onto every generated invoice as the AR Responsible, "
             "which is mandatory on customer invoices here.",
    )

    product_id = fields.Many2one(
        'product.product',
        string='Retainership Product',
        required=True,
        tracking=True,
        domain=[('is_retainership', '=', True)],
        help="Only products ticked as 'Retainership Product' can be put on a "
             "contract.",
    )
    description = fields.Char(
        string='Invoice Line Description',
        help="Line label on the generated invoice. Leave empty to use the "
             "product name. The billed period is appended automatically.",
    )
    quantity = fields.Float(string='Quantity', default=1.0)
    price_unit = fields.Monetary(string='Fee per Period', tracking=True)
    tax_ids = fields.Many2many(
        'account.tax',
        string='Taxes',
        domain=[('type_tax_use', '=', 'sale')],
        help="Left empty, the product's own sales taxes are used. Either way "
             "the client's fiscal position is applied when the draft is "
             "raised.",
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Invoice Journal',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id)]",
        help="Leave empty to use the company's default sales journal.",
    )

    interval = fields.Selection(
        RETAINERSHIP_INTERVALS,
        string='Billing Period',
        required=True,
        default='monthly',
        tracking=True,
    )
    billing_day = fields.Integer(
        string='Bill on Day',
        default=1,
        required=True,
        help="Day of the month the draft is dated and raised on (1-%s)."
             % MAX_BILLING_DAY,
    )
    generation_lead_days = fields.Integer(
        string='Raise Draft N Days Early',
        default=0,
        help="Raise the draft this many days before the invoice date, to give "
             "finance time to review it. 0 raises it on the day itself; the "
             "invoice date is the billing day either way.",
    )

    date_start = fields.Date(
        string='Start Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    date_end = fields.Date(
        string='End Date',
        tracking=True,
        help="Leave empty for an open-ended retainer. No draft is raised for a "
             "period starting after this date.",
    )
    next_invoice_date = fields.Date(
        string='Next Invoice Date',
        compute='_compute_next_invoice_date',
        store=True,
        readonly=False,
        tracking=True,
        copy=False,
        help="Start of the next period to be billed. Advances automatically "
             "each time a draft is raised.",
    )
    last_generated_date = fields.Date(
        string='Last Draft Raised On',
        readonly=True,
        copy=False,
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('running', 'Running'),
            ('paused', 'Paused'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        help="Only Running contracts are picked up by the scheduler.",
    )

    invoice_ids = fields.One2many(
        'account.move',
        'retainership_contract_id',
        string='Generated Invoices',
        readonly=True,
    )
    invoice_count = fields.Integer(
        string='Invoices',
        compute='_compute_invoice_count',
    )
    draft_invoice_count = fields.Integer(
        string='Drafts Awaiting Review',
        compute='_compute_invoice_count',
    )

    # ------------------------------------------------------------------
    # Defaults, computes and validation
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'retainership.contract'
                ) or 'New'
        contracts = super().create(vals_list)
        contracts._sync_engagement_from_sale_line()
        return contracts

    def write(self, vals):
        res = super().write(vals)
        if 'sale_order_line_id' in vals:
            self._sync_engagement_from_sale_line()
        return res

    def _sync_engagement_from_sale_line(self):
        """Pull the engagement off the Sale Order Line's project.

        Only writes when the line actually resolves to a project, so the legacy
        contracts -- whose engagement predates this field and whose project has
        no sale order line -- are never blanked out.
        """
        for contract in self:
            project = contract.sale_order_line_id.sudo().project_id
            if project and contract.service_engagement_id != project:
                contract.service_engagement_id = project

    @api.onchange('sale_order_line_id')
    def _onchange_sale_order_line_id(self):
        for contract in self:
            project = contract.sale_order_line_id.sudo().project_id
            if project:
                contract.service_engagement_id = project

    @api.constrains('sale_order_line_id', 'service_engagement_id')
    def _check_sale_order_line_required(self):
        """Replaces the old `required=True` on the engagement: a contract needs
        a Sale Order Line now, but one carried over with only an engagement is
        still valid so the three pre-existing contracts keep generating."""
        for contract in self:
            if contract.service_engagement_id:
                continue
            if not contract.sale_order_line_id:
                raise ValidationError(
                    "Sale Order Line is mandatory on a retainership contract. "
                    "Please link this contract to a sale order line before saving."
                )
            # A line that delivers no project leaves the generated invoice with
            # neither link, which account.move then refuses to save.
            raise ValidationError(
                "Sale Order Line '%s' is not linked to a project, so the "
                "invoices generated from this contract would have no "
                "engagement. Set the project on the sale order line first."
                % contract.sale_order_line_id.display_name
            )

    @api.depends('date_start', 'billing_day', 'state')
    def _compute_next_invoice_date(self):
        """Seed the schedule from the start date while the contract is still
        being set up. Once it is running the field is only moved by the
        generator (or by hand), so an in-flight schedule is never rewound by
        an edit to the start date."""
        for contract in self:
            if contract.state != 'draft':
                if not contract.next_invoice_date:
                    contract.next_invoice_date = contract.date_start
                continue
            contract.next_invoice_date = contract.date_start

    @api.depends('invoice_ids.state', 'invoice_ids.move_type')
    def _compute_invoice_count(self):
        for contract in self:
            invoices = contract.invoice_ids
            contract.invoice_count = len(invoices)
            contract.draft_invoice_count = len(
                invoices.filtered(lambda m: m.state == 'draft')
            )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        for contract in self:
            product = contract.product_id
            if not product:
                continue
            if product.retainership_interval:
                contract.interval = product.retainership_interval
            if product.retainership_billing_day:
                contract.billing_day = product.retainership_billing_day
            if not contract.description:
                contract.description = product.get_product_multiline_description_sale()
            if not contract.price_unit:
                contract.price_unit = product.lst_price
            if not contract.tax_ids:
                contract.tax_ids = product.taxes_id.filtered(
                    lambda t: t.company_id == contract.company_id
                )

    @api.constrains('billing_day')
    def _check_billing_day(self):
        for contract in self:
            if not 1 <= contract.billing_day <= MAX_BILLING_DAY:
                raise ValidationError(
                    "Bill on Day must be between 1 and %s (a higher day does "
                    "not exist in every month)." % MAX_BILLING_DAY
                )

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for contract in self:
            if contract.date_end and contract.date_end < contract.date_start:
                raise ValidationError(
                    "End Date cannot be earlier than Start Date on %s."
                    % contract.display_name
                )

    @api.constrains('product_id')
    def _check_product_is_retainership(self):
        for contract in self:
            if contract.product_id and not contract.product_id.is_retainership:
                raise ValidationError(
                    "'%s' is not marked as a Retainership Product. Tick "
                    "'Retainership Product' on the product first, or pick "
                    "another product."
                    % contract.product_id.display_name
                )

    # ------------------------------------------------------------------
    # Schedule arithmetic
    # ------------------------------------------------------------------

    def _snap_to_billing_day(self, date):
        """Move a date onto the contract's billing day within its own month."""
        self.ensure_one()
        day = min(self.billing_day, calendar.monthrange(date.year, date.month)[1])
        return date.replace(day=day)

    def _next_period_start(self, period_start):
        """Start of the period following the one that opens on period_start.

        Advancing by whole months and then snapping to the billing day keeps a
        contract that starts mid-month on the client's billing day from the
        second period onwards: a retainer starting 15 Jan with billing day 1
        bills 15-31 Jan as a short first period, then 1 Feb, 1 Mar, ...
        """
        self.ensure_one()
        months = RETAINERSHIP_INTERVAL_MONTHS[self.interval]
        return self._snap_to_billing_day(period_start + relativedelta(months=months))

    def _period_label(self, period_start, period_end):
        self.ensure_one()
        fmt = '%d %b %Y'
        return "%s - %s" % (period_start.strftime(fmt), period_end.strftime(fmt))

    # ------------------------------------------------------------------
    # Draft generation
    # ------------------------------------------------------------------

    def _prepare_invoice_line_vals(self, period_start, period_end):
        self.ensure_one()
        fiscal_position = self.env['account.fiscal.position'].with_company(
            self.company_id
        )._get_fiscal_position(self.partner_id)
        taxes = self.tax_ids or self.product_id.taxes_id.filtered(
            lambda t: t.company_id == self.company_id
        )
        if fiscal_position:
            taxes = fiscal_position.map_tax(taxes)
        label = self.description or self.product_id.display_name
        vals = {
            'product_id': self.product_id.id,
            'name': "%s\nRetainership period: %s" % (
                label, self._period_label(period_start, period_end),
            ),
            'quantity': self.quantity,
            'price_unit': self.price_unit,
            'tax_ids': [Command.set(taxes.ids)],
        }
        # Carry the engagement's analytic account so retainer revenue lands on
        # the same analytic as the rest of the engagement's billing.
        analytic = self.service_engagement_id.account_id \
            if 'account_id' in self.service_engagement_id._fields else False
        if analytic:
            vals['analytic_distribution'] = {str(analytic.id): 100.0}
        return vals

    def _prepare_invoice_vals(self, period_start, period_end):
        self.ensure_one()
        return {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'invoice_date': period_start,
            'invoice_origin': self.name,
            'journal_id': self.journal_id.id or False,
            # The engagement is what is stamped: the invoice's own Sale Order
            # Line then resolves itself from it. Deliberately not writing
            # sale_line_ids onto the invoice line -- that would count retainer
            # billing against the sale order line's invoiced quantity and can
            # close out the order.
            'ar_responsible_id': self.ar_responsible_id.id,
            'service_engagement_id': self.service_engagement_id.id,
            # invoice_type_classification is derived from retainership_contract_id
            # below, so it is not set here.
            'retainership_contract_id': self.id,
            'retainership_period_start': period_start,
            'retainership_period_end': period_end,
            'is_retainership_auto': True,
            'invoice_line_ids': [
                Command.create(self._prepare_invoice_line_vals(period_start, period_end)),
            ],
        }

    def _existing_invoice_for_period(self, period_start):
        """A draft already raised for this period, so a re-run of the cron (or
        a manual 'Generate Draft Now' on top of it) never bills twice."""
        self.ensure_one()
        return self.env['account.move'].search([
            ('retainership_contract_id', '=', self.id),
            ('retainership_period_start', '=', period_start),
            ('state', '!=', 'cancel'),
        ], limit=1)

    def _schedule_review_activity(self, move, period_start, period_end):
        """Put the draft in front of the finance reviewers.

        Reviewers are whoever has the 'Retainership Invoice Reviewer' box
        ticked on their user record, so the list is maintained in Settings and
        never in code. With nobody ticked the AR Responsible is asked instead,
        rather than the draft sitting unnoticed.
        """
        self.ensure_one()
        group = self.env.ref(
            'account_extended_rk.group_retainership_reviewer',
            raise_if_not_found=False,
        )
        reviewers = group.users.filtered(
            lambda u: u.active and not u.share
        ) if group else self.env['res.users']
        if not reviewers:
            reviewers = self.ar_responsible_id
        note = (
            "Auto-generated from retainership contract %s for %s.<br/>"
            "Period billed: %s.<br/>"
            "Review the amount, period and taxes, then post the invoice to "
            "approve it for sending to the client."
        ) % (
            self.name,
            self.partner_id.display_name,
            self._period_label(period_start, period_end),
        )
        for reviewer in reviewers:
            move.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=reviewer.id,
                summary=REVIEW_ACTIVITY_SUMMARY,
                note=note,
                date_deadline=period_start,
            )

    def _generate_period_invoice(self, period_start, period_end):
        """Raise (or return the already-raised) draft for one period."""
        self.ensure_one()
        existing = self._existing_invoice_for_period(period_start)
        if existing:
            return existing
        move = self.env['account.move'].with_company(self.company_id).create(
            self._prepare_invoice_vals(period_start, period_end)
        )
        self._schedule_review_activity(move, period_start, period_end)
        full_period = self._next_period_start(period_start) - relativedelta(days=1)
        short_note = ""
        if period_end < full_period:
            short_note = (
                " This first period is shorter than a full %s cycle - check "
                "whether the fee should be pro-rated before posting."
                % dict(RETAINERSHIP_INTERVALS)[self.interval].lower()
            )
        self.message_post(
            body="Draft invoice %s raised for period %s.%s" % (
                move._get_html_link() if hasattr(move, '_get_html_link') else move.display_name,
                self._period_label(period_start, period_end),
                short_note,
            )
        )
        move.message_post(
            body="Draft raised automatically from retainership contract %s "
                 "for the period %s. Awaiting finance review - posting this "
                 "invoice approves it." % (
                     self.name, self._period_label(period_start, period_end),
                 )
        )
        return move

    def _generate_due_invoices(self, today=None, force=False):
        """Raise every draft this contract owes as of today.

        force ignores the lead-time window (the manual button), but never the
        schedule itself: a period that has not started yet is still not billed.
        """
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        moves = self.env['account.move']
        if self.state != 'running':
            return moves
        period_start = self.next_invoice_date or self.date_start
        for _i in range(MAX_CATCHUP_PERIODS):
            if self.date_end and period_start > self.date_end:
                self.state = 'expired'
                self.message_post(
                    body="Contract expired: the next period would start on %s, "
                         "past the end date %s." % (period_start, self.date_end)
                )
                break
            trigger_date = period_start - relativedelta(days=max(self.generation_lead_days, 0))
            if today < trigger_date and not force:
                break
            if force and today < period_start:
                break
            period_end = self._next_period_start(period_start) - relativedelta(days=1)
            if self.date_end and period_end > self.date_end:
                period_end = self.date_end
            moves |= self._generate_period_invoice(period_start, period_end)
            period_start = self._next_period_start(period_start)
            self.write({
                'next_invoice_date': period_start,
                'last_generated_date': today,
            })
            if force:
                # One click, one draft: catch-up is the scheduler's job.
                break
        else:
            _logger.warning(
                "Retainership contract %s hit the %s-period catch-up cap in a "
                "single run; remaining periods will be raised on the next run.",
                self.name, MAX_CATCHUP_PERIODS,
            )
        return moves

    @api.model
    def _cron_generate_retainership_invoices(self):
        """Daily: raise the draft invoices every running contract owes.

        Each contract is generated inside its own savepoint - a contract with,
        say, an archived engagement fails its own validation without taking
        the rest of the run down with it.
        """
        today = fields.Date.context_today(self)
        contracts = self.search([
            ('state', '=', 'running'),
            '|', ('date_end', '=', False), ('date_end', '>=', today),
        ])
        generated = 0
        for contract in contracts:
            try:
                with self.env.cr.savepoint():
                    moves = contract._generate_due_invoices(today)
                    generated += len(moves)
            except Exception as error:  # noqa: BLE001 - one bad contract must not stop the run
                _logger.exception(
                    "Retainership contract %s failed to generate its draft invoice",
                    contract.name,
                )
                contract.message_post(
                    body="Automatic draft generation failed for this contract: "
                         "%s<br/>The scheduler will retry tomorrow." % error
                )
        # Contracts whose end date has passed are closed off so they stop being
        # scanned every day.
        expired = self.search([
            ('state', '=', 'running'),
            ('date_end', '!=', False),
            ('date_end', '<', today),
        ])
        if expired:
            expired.write({'state': 'expired'})
        _logger.info(
            "Retainership: %s contract(s) scanned, %s draft invoice(s) raised, "
            "%s contract(s) expired.", len(contracts), generated, len(expired),
        )
        return True

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def action_start(self):
        for contract in self:
            if contract.state not in ('draft', 'paused'):
                raise UserError(
                    "Only a draft or paused contract can be started (%s is %s)."
                    % (contract.display_name, contract.state)
                )
            if contract.price_unit <= 0:
                raise UserError(
                    "Set a Fee per Period on %s before starting it."
                    % contract.display_name
                )
            if not contract.next_invoice_date:
                contract.next_invoice_date = contract.date_start
            contract.state = 'running'
            contract.message_post(
                body="Contract started. Next draft invoice due on %s."
                     % contract.next_invoice_date
            )

    def action_pause(self):
        for contract in self:
            if contract.state != 'running':
                raise UserError(
                    "Only a running contract can be paused (%s is %s)."
                    % (contract.display_name, contract.state)
                )
            contract.state = 'paused'
            contract.message_post(body="Contract paused - no drafts will be raised.")

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        for contract in self:
            contract.message_post(body="Contract cancelled.")

    def action_reset_to_draft(self):
        for contract in self:
            if contract.state == 'running':
                raise UserError(
                    "Pause %s before resetting it to draft." % contract.display_name
                )
            contract.state = 'draft'

    def action_generate_now(self):
        """Raise the current due draft by hand, outside the daily schedule."""
        moves = self.env['account.move']
        for contract in self:
            if contract.state != 'running':
                raise UserError(
                    "Start %s before generating a draft from it."
                    % contract.display_name
                )
            moves |= contract._generate_due_invoices(force=True)
        if not moves:
            raise UserError(
                "Nothing to bill yet: the next period starts on %s."
                % ", ".join(str(c.next_invoice_date) for c in self)
            )
        if len(moves) == 1:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.move',
                'res_id': moves.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return self.action_view_invoices()

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Retainership Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('retainership_contract_id', '=', self.id)],
            'context': {'create': False},
        }
