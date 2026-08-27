import re

from odoo import models, fields, api, _
from odoo.tools.misc import format_date, formatLang

# Engagements are identified by the sale order name, e.g. "SE07791". Project
# names are built as "<SE code> - <product> - <line>" by _create_project_and_tasks,
# but plenty of older projects were typed in by hand, so the code is recovered
# from the name after stripping punctuation, spacing and stray zero-width
# characters (several project names start with one).
SE_CODE_RE = re.compile(r'^(SE\d+)')


def _extract_se_code(name):
    if not name:
        return False
    cleaned = re.sub(r'[^A-Za-z0-9]', '', name).upper()
    match = SE_CODE_RE.match(cleaned)
    return match.group(1) if match else False


def _invoice_label(move):
    """Draft moves carry the placeholder name "/" — show something readable."""
    name = (move.name or '').strip()
    return name if name and name != '/' else _("Draft invoice")


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # --- the engagement behind the project -------------------------------
    engagement_order_id = fields.Many2one(
        'sale.order',
        string="Engagement (SE)",
        compute='_compute_engagement_order_id',
        store=True,
        readonly=False,
        index='btree_not_null',
        help="Sale order this engagement letter belongs to. Resolved from the "
             "linked sale order line, or from the SE code in the project name. "
             "Editable - set it by hand when the name does not carry the code.",
    )

    # --- engagement letter ------------------------------------------------
    engagement_letter_sent_date = fields.Datetime(
        string="Letter Sent On",
        compute='_compute_engagement_letter_sent_date',
        store=True,
        readonly=False,
        help="Filled automatically when the Service Engagement letter is "
             "generated on the sale order. Set it by hand for letters that were "
             "issued outside Odoo.",
    )
    engagement_letter_sent = fields.Boolean(
        string="Letter Sent",
        compute='_compute_engagement_letter_flags',
        store=True,
    )
    engagement_letter_signed_date = fields.Datetime(
        string="Date Signed",
        compute='_compute_engagement_letter_signed_date',
        store=True,
        readonly=False,
        help="Filled automatically when the client signs the order. Set it by "
             "hand for letters signed on paper.",
    )
    engagement_letter_signed = fields.Boolean(
        string="Client Signed",
        compute='_compute_engagement_letter_flags',
        store=True,
    )
    engagement_signed_by = fields.Char(
        string="Signed By",
        related='engagement_order_id.signed_by',
        readonly=True,
    )

    # --- advance fee invoice ----------------------------------------------
    advance_invoice_id = fields.Many2one(
        'account.move',
        string="Advance Invoice",
        compute='_compute_advance_invoice',
        store=True,
        groups='account.group_account_readonly',
    )
    advance_invoice_status = fields.Selection(
        [
            ('not_required', 'Not Required'),
            ('not_created', 'Not Raised'),
            ('draft', 'Draft'),
            ('posted', 'Posted - Unpaid'),
            ('partial', 'Partially Paid'),
            ('paid', 'Paid'),
        ],
        string="Advance Invoice",
        compute='_compute_advance_invoice',
        store=True,
        default='not_required',
        help="Not Required: no advance fee agreed on the order. "
             "Not Raised: an advance was agreed but no invoice exists yet.",
    )

    # --- roll-up used for the status filter -------------------------------
    engagement_status = fields.Selection(
        [
            ('no_order', 'No Engagement Linked'),
            ('not_sent', 'Letter Not Sent'),
            ('awaiting_signature', 'Awaiting Signature'),
            ('signed', 'Signed'),
        ],
        string="Engagement Status",
        compute='_compute_engagement_status',
        store=True,
        default='no_order',
    )

    @api.depends('name', 'sale_line_id')
    def _compute_engagement_order_id(self):
        # Resolve every SE code in one search rather than one per project -
        # this runs over ~3.1k projects on upgrade.
        codes = {}
        for project in self:
            if not project.sale_line_id:
                code = _extract_se_code(project.name)
                if code:
                    codes[project.id] = code
        orders_by_name = {}
        if codes:
            orders = self.env['sale.order'].sudo().search(
                [('name', 'in', list(set(codes.values())))]
            )
            orders_by_name = {order.name: order.id for order in orders}
        for project in self:
            if project.sale_line_id:
                project.engagement_order_id = project.sale_line_id.order_id
                continue
            code = codes.get(project.id)
            project.engagement_order_id = orders_by_name.get(code, False)

    @api.depends('engagement_order_id', 'engagement_order_id.se_generated_on')
    def _compute_engagement_letter_sent_date(self):
        for project in self:
            generated_on = project.engagement_order_id.sudo().se_generated_on
            # Never wipe a date somebody recorded by hand.
            if generated_on or not project.engagement_letter_sent_date:
                project.engagement_letter_sent_date = generated_on

    @api.depends('engagement_order_id', 'engagement_order_id.signed_on')
    def _compute_engagement_letter_signed_date(self):
        for project in self:
            signed_on = project.engagement_order_id.sudo().signed_on
            if signed_on or not project.engagement_letter_signed_date:
                project.engagement_letter_signed_date = signed_on

    @api.depends('engagement_letter_sent_date', 'engagement_letter_signed_date')
    def _compute_engagement_letter_flags(self):
        for project in self:
            project.engagement_letter_signed = bool(project.engagement_letter_signed_date)
            # A signed letter was necessarily sent, whatever the sent date says.
            project.engagement_letter_sent = bool(
                project.engagement_letter_sent_date or project.engagement_letter_signed_date
            )

    @api.depends(
        'engagement_order_id',
        'engagement_order_id.advance_amount',
        'engagement_order_id.order_line.invoice_lines.move_id.state',
        'engagement_order_id.order_line.invoice_lines.move_id.payment_state',
    )
    def _compute_advance_invoice(self):
        for project in self:
            order = project.engagement_order_id.sudo()
            if not order or not order.advance_amount:
                project.advance_invoice_id = False
                project.advance_invoice_status = 'not_required'
                continue

            invoices = order.order_line.invoice_lines.move_id.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
            # Prefer an invoice explicitly flagged as the advance; otherwise the
            # first invoice raised on the engagement is the advance fee.
            invoice = invoices.filtered('advance_invoice')[:1] or invoices.sorted('id')[:1]
            if not invoice:
                project.advance_invoice_id = False
                project.advance_invoice_status = 'not_created'
                continue

            project.advance_invoice_id = invoice
            if invoice.state == 'draft':
                project.advance_invoice_status = 'draft'
            elif invoice.payment_state in ('paid', 'in_payment', 'reversed'):
                project.advance_invoice_status = 'paid'
            elif invoice.payment_state == 'partial':
                project.advance_invoice_status = 'partial'
            else:
                project.advance_invoice_status = 'posted'

    @api.depends('engagement_order_id', 'engagement_letter_sent', 'engagement_letter_signed')
    def _compute_engagement_status(self):
        for project in self:
            if not project.engagement_order_id:
                project.engagement_status = 'no_order'
            elif project.engagement_letter_signed:
                project.engagement_status = 'signed'
            elif project.engagement_letter_sent:
                project.engagement_status = 'awaiting_signature'
            else:
                project.engagement_status = 'not_sent'


class ProjectInvoiceAlert(models.Model):
    """Engagement-level red/amber flag for overdue or unreconciled invoices.

    Every field here is deliberately a plain scalar or text: a Project Manager,
    team lead or department head has *no* read access to ``account.move`` in this
    database (only Advisor / Auditor / Invoicing / salesman do — see
    ir_model_access), so exposing an invoice o2m on the project form would raise
    an AccessError for exactly the people this indicator is for. Everything is
    resolved under ``sudo()`` and denormalised onto the project, which is what
    lets the flag — and the invoice detail behind it — be read without opening
    the invoice module at all.
    """
    _inherit = 'project.project'

    # Payment states that mean "nothing left to collect".
    _SETTLED_PAYMENT_STATES = ('paid', 'in_payment', 'reversed')

    invoice_alert_state = fields.Selection(
        [
            ('none', 'No Invoice'),
            ('ok', 'Settled'),
            ('warning', 'Attention'),
            ('overdue', 'Overdue'),
        ],
        string="Invoice Flag",
        compute='_compute_invoice_alert',
        store=True,
        default='none',
        index='btree_not_null',
        help="Red (Overdue): at least one posted invoice on this engagement is "
             "past its due date and still unpaid. "
             "Amber (Attention): nothing is past due yet, but the engagement has "
             "an unreconciled posted invoice or an invoice still sitting in draft. "
             "Green (Settled): every invoice raised on the engagement is fully "
             "reconciled. Grey (No Invoice): nothing has been billed yet.",
    )
    overdue_invoice_count = fields.Integer(
        string="Overdue Invoices",
        compute='_compute_invoice_alert',
        store=True,
    )
    overdue_invoice_amount = fields.Monetary(
        string="Overdue Amount",
        compute='_compute_invoice_alert',
        store=True,
        currency_field='currency_id',
    )
    unreconciled_invoice_count = fields.Integer(
        string="Unreconciled Invoices",
        compute='_compute_invoice_alert',
        store=True,
        help="Posted customer invoices on this engagement that still carry an "
             "open balance, whether or not they are past due.",
    )
    unreconciled_invoice_amount = fields.Monetary(
        string="Unreconciled Amount",
        compute='_compute_invoice_alert',
        store=True,
        currency_field='currency_id',
    )
    draft_invoice_count = fields.Integer(
        string="Draft Invoices",
        compute='_compute_invoice_alert',
        store=True,
        help="Invoices raised on this engagement that were never posted, so no "
             "receivable exists for them yet.",
    )
    invoice_days_overdue = fields.Integer(
        string="Days Overdue",
        compute='_compute_invoice_alert',
        store=True,
        help="Age of the oldest overdue invoice on this engagement, in days.",
    )
    invoice_alert_summary = fields.Text(
        string="Invoice Position",
        compute='_compute_invoice_alert_summary',
        help="Line-by-line breakdown of the invoices behind the flag, so the "
             "engagement owner never has to open Accounting to act on it.",
    )

    # --- invoice resolution ------------------------------------------------
    def _engagement_invoice_map(self):
        """Return ``{project.id: account.move recordset}`` of customer invoices.

        An engagement is billed through its sale order, so the invoices are the
        ones posted against that order's lines. The tasks' own ``sale_line_id``
        is unioned in as well: it is how the older, hand-made projects were tied
        to their order before ``engagement_order_id`` existed. In practice the
        engagement path resolves 2,085 of 3,161 active projects and the task path
        adds one more, but the union costs nothing and keeps the flag honest for
        projects whose name never carried an SE code.
        """
        # sudo() from the very first hop, not just at the account.move read:
        # the sale.order / sale.order.line record rules silently filter an
        # inaccessible order's lines down to an empty o2m rather than raising, so
        # a PM reading this without sudo sees an engagement with no invoices at
        # all instead of their overdue one.
        lines_by_project = {
            project.id: project.engagement_order_id.order_line | project.task_ids.sale_line_id
            for project in self.sudo()
        }
        # One prefetch for the whole batch — this compute runs over every active
        # project on upgrade.
        all_line_ids = set()
        for lines in lines_by_project.values():
            all_line_ids.update(lines.ids)
        if all_line_ids:
            self.env['sale.order.line'].sudo().browse(sorted(all_line_ids)).mapped(
                'invoice_lines.move_id.amount_residual'
            )
        empty = self.env['account.move'].sudo()
        result = {}
        for project in self:
            lines = lines_by_project[project.id]
            if not lines:
                result[project.id] = empty
                continue
            result[project.id] = lines.sudo().invoice_lines.move_id.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
        return result

    def _alert_currency(self):
        """Currency to round residuals against.

        ``currency_id`` is related to ``company_id.currency_id``, and during the
        upgrade recompute both can still be empty for a project — falling through
        to the environment company keeps ``is_zero`` from blowing up on an empty
        recordset.
        """
        self.ensure_one()
        return (
            self.currency_id
            or self.company_id.currency_id
            or self.env.company.currency_id
        )

    def _split_engagement_invoices(self, moves, today):
        """Split one engagement's invoices into (overdue, not-yet-due, draft).

        ``overdue`` and ``pending`` are both unreconciled — they differ only on
        whether the due date has passed. An invoice with no due date at all falls
        back to its invoice date; with neither, it cannot be called late, so it
        counts as pending rather than overdue.
        """
        empty = self.env['account.move'].sudo()
        overdue, pending = empty, empty
        draft = moves.filtered(lambda m: m.state == 'draft')
        currency = self._alert_currency()
        for move in moves.filtered(lambda m: m.state == 'posted'):
            if move.payment_state in self._SETTLED_PAYMENT_STATES:
                continue
            if currency.is_zero(move.amount_residual):
                continue
            due_date = move.invoice_date_due or move.invoice_date
            if due_date and due_date < today:
                overdue |= move
            else:
                pending |= move
        return overdue, pending, draft

    @api.depends(
        'currency_id',
        'engagement_order_id',
        'engagement_order_id.order_line.invoice_lines.move_id.state',
        'engagement_order_id.order_line.invoice_lines.move_id.payment_state',
        'engagement_order_id.order_line.invoice_lines.move_id.amount_residual',
        'engagement_order_id.order_line.invoice_lines.move_id.invoice_date_due',
        'task_ids.sale_line_id.invoice_lines.move_id.state',
        'task_ids.sale_line_id.invoice_lines.move_id.payment_state',
        'task_ids.sale_line_id.invoice_lines.move_id.amount_residual',
        'task_ids.sale_line_id.invoice_lines.move_id.invoice_date_due',
    )
    def _compute_invoice_alert(self):
        today = fields.Date.context_today(self)
        invoices_by_project = self._engagement_invoice_map()
        empty = self.env['account.move'].sudo()
        for project in self:
            moves = invoices_by_project.get(project.id, empty)
            overdue, pending, draft = project._split_engagement_invoices(moves, today)

            project.overdue_invoice_count = len(overdue)
            project.overdue_invoice_amount = sum(overdue.mapped('amount_residual'))
            project.unreconciled_invoice_count = len(overdue) + len(pending)
            project.unreconciled_invoice_amount = sum(
                (overdue | pending).mapped('amount_residual')
            )
            project.draft_invoice_count = len(draft)
            project.invoice_days_overdue = max(
                (
                    (today - (move.invoice_date_due or move.invoice_date)).days
                    for move in overdue
                ),
                default=0,
            )

            if overdue:
                project.invoice_alert_state = 'overdue'
            elif pending or draft:
                project.invoice_alert_state = 'warning'
            elif moves:
                project.invoice_alert_state = 'ok'
            else:
                project.invoice_alert_state = 'none'

    @api.depends('invoice_alert_state')
    def _compute_invoice_alert_summary(self):
        today = fields.Date.context_today(self)
        invoices_by_project = self._engagement_invoice_map()
        empty = self.env['account.move'].sudo()
        for project in self:
            moves = invoices_by_project.get(project.id, empty)
            overdue, pending, draft = project._split_engagement_invoices(moves, today)
            currency = project._alert_currency()

            lines = []
            for move in overdue.sorted(lambda m: m.invoice_date_due or m.invoice_date):
                due_date = move.invoice_date_due or move.invoice_date
                lines.append(_(
                    "%(name)s - due %(due)s (%(days)s days overdue) - %(amount)s open",
                    name=_invoice_label(move),
                    due=format_date(self.env, due_date),
                    days=(today - due_date).days,
                    amount=formatLang(self.env, move.amount_residual, currency_obj=currency),
                ))
            for move in pending.sorted(lambda m: m.invoice_date_due or m.invoice_date or today):
                due_date = move.invoice_date_due or move.invoice_date
                lines.append(_(
                    "%(name)s - due %(due)s - %(amount)s open",
                    name=_invoice_label(move),
                    due=format_date(self.env, due_date) if due_date else _("no due date"),
                    amount=formatLang(self.env, move.amount_residual, currency_obj=currency),
                ))
            for move in draft.sorted('id'):
                lines.append(_(
                    "%(name)s - still in draft, not posted - %(amount)s",
                    name=_invoice_label(move),
                    amount=formatLang(self.env, move.amount_total, currency_obj=currency),
                ))

            if not lines:
                lines = [
                    _("Every invoice raised on this engagement is fully reconciled.")
                    if moves else
                    _("No customer invoice has been raised on this engagement yet.")
                ]
            project.invoice_alert_summary = "\n".join(lines)

    # --- drill-down for the accounting-privileged ---------------------------
    def action_view_engagement_invoices(self):
        """Open the invoices behind the flag.

        Only offered to users who can read ``account.move``; everyone else works
        off ``invoice_alert_summary`` on the project form.
        """
        self.ensure_one()
        move_ids = self._engagement_invoice_map().get(
            self.id, self.env['account.move']
        ).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _("Engagement Invoices"),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', move_ids)],
            'context': {'create': False},
        }
