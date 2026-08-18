from odoo import models, fields, api
from odoo.exceptions import ValidationError

LATE_PAYMENT_PENALTY_TEXT = (
    "Late payment penalty: AED 50 per day will be charged on all overdue "
    "invoices from the due date until settlement."
)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # Locked footer clause: not editable per-invoice, always recomputed for
    # customer invoices/credit notes so it can't be removed or altered.
    narration = fields.Html(readonly=True)

    ar_responsible_id = fields.Many2one(
        'res.users',
        string='AR Responsible',
        domain=[('share', '=', False)],
        tracking=True,
        help="User responsible for following up on collection of this invoice.",
    )

    service_engagement_id = fields.Many2one(
        'project.project',
        string='Bill To / Linked Service Engagement',
        tracking=True,
        help="Service engagement (project) this invoice is billed against. Mandatory on customer invoices and credit notes.",
    )

    invoice_type_classification = fields.Selection(
        [
            ('advance', 'Advance'),
            ('completion', 'Completion'),
            ('retainer', 'Retainer'),
            ('credit_note', 'Credit Note'),
        ],
        string='Invoice Type',
        tracking=True,
        copy=False,
        help="Classifies the AR document for the receivables dashboard split view. "
             "Mandatory on customer invoices and credit notes.",
    )

    followup_log_ids = fields.One2many(
        'account.invoice.followup.log',
        'move_id',
        string='Follow-up Log',
    )

    last_followup_date = fields.Date(
        string='Last Follow-up Date',
        compute='_compute_last_followup',
        store=True,
    )
    last_followup_method = fields.Selection(
        [
            ('email', 'Email'),
            ('call', 'Call'),
            ('whatsapp', 'WhatsApp'),
        ],
        string='Last Follow-up Method',
        compute='_compute_last_followup',
        store=True,
    )
    last_followup_response = fields.Text(
        string='Last Client Response',
        compute='_compute_last_followup',
        store=True,
    )

    followup_log_status = fields.Selection(
        [('present', 'Present'), ('missing', 'Missing')],
        string='Follow-up Log Status',
        compute='_compute_followup_log_status',
        store=True,
    )

    engagement_team_id = fields.Many2one(
        'hr.department',
        string='Team',
        related='service_engagement_id.department_id',
        store=True,
    )

    engagement_pm_id = fields.Many2one(
        'res.users',
        string='PM',
        related='service_engagement_id.user_id',
        store=True,
    )

    # ── Delivery people behind the invoice ────────────────────────────────
    project_manager_ids = fields.Many2many(
        'res.users',
        'account_move_project_manager_rel', 'move_id', 'user_id',
        string='Project Manager',
        compute='_compute_project_manager_ids', store=True,
        help="Managers set on the sale order lines this invoice bills.")

    project_team_member_ids = fields.Many2many(
        'res.users',
        string='Team Member',
        compute='_compute_project_team_member_ids',
        help="Team members on the still-open tasks of the projects linked to "
             "this invoice's sale orders.")

    @api.depends('invoice_line_ids.sale_line_ids.manager_id')
    def _compute_project_manager_ids(self):
        for move in self:
            move.project_manager_ids = move.invoice_line_ids.sale_line_ids.manager_id

    def _compute_project_team_member_ids(self):
        """Invoice -> sale orders -> projects -> open tasks -> team members.

        A project is tied to an order three ways in this database: the project's
        own Sales Order field, the task's Sales Order field, or the sale order
        line the task was generated from. All three are followed, otherwise the
        column stays empty for almost every invoice.

        Not stored: it tracks the *currently* open tasks, and there is no ORM
        dependency path from an invoice down to them. Resolved in one search for
        the whole batch so the list view stays cheap.
        """
        orders_by_move = {
            move: move.invoice_line_ids.sale_line_ids.order_id for move in self}
        order_ids = set().union(*[o.ids for o in orders_by_move.values()]) if self else set()
        if not order_ids:
            for move in self:
                move.project_team_member_ids = [(5, 0, 0)]
            return

        order_ids = list(order_ids)
        tasks = self.env['project.task'].search([
            ('is_closed', '=', False),
            ('team_member_ids', '!=', False),
            '|', '|',
            ('project_id.sale_order_id', 'in', order_ids),
            ('sale_order_id', 'in', order_ids),
            ('sale_line_id.order_id', 'in', order_ids),
        ])

        members_by_order = {}
        for task in tasks:
            for order in (task.project_id.sale_order_id, task.sale_order_id,
                          task.sale_line_id.order_id):
                if order and order.id in order_ids:
                    members_by_order.setdefault(order.id, set()).update(
                        task.team_member_ids.ids)

        for move in self:
            member_ids = set()
            for order in orders_by_move[move]:
                member_ids |= members_by_order.get(order.id, set())
            move.project_team_member_ids = [(6, 0, list(member_ids))]

    invoice_age_days = fields.Integer(
        string='Invoice Age (Days)',
        compute='_compute_ar_aging',
        store=True,
        help="Days past the due date. 0 while not yet due or once settled.",
    )

    aging_bucket = fields.Selection(
        [
            ('not_due', 'Not Due'),
            ('0_30', '0-30 Days'),
            ('31_60', '31-60 Days'),
            ('61_90', '61-90 Days'),
            ('90_plus', '90+ Days'),
        ],
        string='Aging Bucket',
        compute='_compute_ar_aging',
        store=True,
    )

    credit_hold = fields.Boolean(
        string='Credit Hold',
        compute='_compute_credit_hold',
        store=True,
        help="Client's outstanding receivable balance exceeds their credit limit.",
    )

    def _compute_narration(self):
        super()._compute_narration()
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund'):
                move.narration = LATE_PAYMENT_PENALTY_TEXT

    @api.depends('followup_log_ids.date', 'followup_log_ids.method', 'followup_log_ids.response')
    def _compute_last_followup(self):
        for move in self:
            last = move.followup_log_ids[:1]
            move.last_followup_date = last.date
            move.last_followup_method = last.method
            move.last_followup_response = last.response

    @api.depends('followup_log_ids')
    def _compute_followup_log_status(self):
        for move in self:
            move.followup_log_status = 'present' if move.followup_log_ids else 'missing'

    @api.depends('invoice_date_due', 'state', 'payment_state', 'move_type')
    def _compute_ar_aging(self):
        today = fields.Date.context_today(self)
        for move in self:
            is_outstanding = (
                move.state == 'posted'
                and move.move_type == 'out_invoice'
                and move.payment_state in ('not_paid', 'partial')
            )
            if not is_outstanding or not move.invoice_date_due:
                move.invoice_age_days = 0
                move.aging_bucket = False
                continue

            due = fields.Date.to_date(move.invoice_date_due)
            delta = (today - due).days
            move.invoice_age_days = max(0, delta)

            if delta <= 0:
                move.aging_bucket = 'not_due'
            elif delta <= 30:
                move.aging_bucket = '0_30'
            elif delta <= 60:
                move.aging_bucket = '31_60'
            elif delta <= 90:
                move.aging_bucket = '61_90'
            else:
                move.aging_bucket = '90_plus'

    @api.depends('partner_id.credit_limit', 'partner_id.credit')
    def _compute_credit_hold(self):
        for move in self:
            partner = move.partner_id
            move.credit_hold = bool(
                partner and partner.credit_limit and partner.credit > partner.credit_limit
            )

    @api.model
    def _cron_refresh_ar_aging(self):
        """invoice_date_due passing, and partner.credit moving as other invoices/
        payments are posted, don't themselves trigger recompute of these stored
        fields, so a daily cron nudges outstanding invoices."""
        moves = self.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])
        moves._compute_ar_aging()
        moves._compute_credit_hold()

    @api.constrains('ar_responsible_id', 'move_type')
    def _check_ar_responsible_required(self):
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and not move.ar_responsible_id:
                raise ValidationError(
                    "AR Responsible is mandatory on customer invoices and credit notes. "
                    "Please set an AR Responsible before saving."
                )

    @api.constrains('service_engagement_id', 'move_type')
    def _check_service_engagement_required(self):
        for move in self:
            if move.move_type in ('out_invoice', 'out_refund') and not move.service_engagement_id:
                raise ValidationError(
                    "Bill To / Linked Service Engagement is mandatory on customer invoices and credit notes. "
                    "Please link this invoice to a service engagement before saving."
                )

    @api.onchange('move_type')
    def _onchange_move_type_invoice_type_classification(self):
        for move in self:
            if move.move_type == 'out_refund':
                move.invoice_type_classification = 'credit_note'
            elif move.invoice_type_classification == 'credit_note' and move.move_type != 'out_refund':
                move.invoice_type_classification = False

    @api.constrains('invoice_type_classification', 'move_type')
    def _check_invoice_type_classification_required(self):
        for move in self:
            if move.move_type not in ('out_invoice', 'out_refund'):
                continue
            if not move.invoice_type_classification:
                raise ValidationError(
                    "Invoice Type is mandatory on customer invoices and credit notes. "
                    "Please set it before saving."
                )
            if move.move_type == 'out_refund' and move.invoice_type_classification != 'credit_note':
                raise ValidationError(
                    "This document is a credit note and must be classified as 'Credit Note'."
                )
            if move.move_type == 'out_invoice' and move.invoice_type_classification == 'credit_note':
                raise ValidationError(
                    "This document is a customer invoice and cannot be classified as 'Credit Note'. "
                    "Use Advance, Completion, or Retainer."
                )

