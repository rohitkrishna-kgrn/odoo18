import base64
import logging

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup

_logger = logging.getLogger(__name__)

# Documents that must be present before an upselling request can be submitted.
# (binary field, filename field, label shown to the user)
REQUIRED_DOCUMENTS = [
    ('proposal_file', 'proposal_filename', 'Proposal File / Email Screenshot'),
    ('engagement_file', 'engagement_filename', 'Engagement Letter'),
    ('receipt_voucher_file', 'receipt_voucher_filename', 'Receipt Voucher'),
]

DEFAULT_ALLOWED_EXTENSIONS = 'pdf,doc,docx,xls,xlsx,png,jpg,jpeg,gif,msg,eml'
DEFAULT_MAX_FILE_SIZE_MB = 10

# Claim periods run from this day of the month to the day before it in the next
# month (e.g. 25 -> cycles of 25th..24th). Set to 1 for plain calendar months.
DEFAULT_CYCLE_START_DAY = 25


class Upselling(models.Model):
    _name = 'upselling'
    _description = 'Upselling'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='Submitted By',
        default=lambda self: self.env.user, readonly=True
    )
    description = fields.Text(string='Description', tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Sale Order', tracking=True)
    customer_id = fields.Many2one('res.partner', string='Customer', readonly=True, tracking=True)
    proposal_file = fields.Binary(string='Proposal File / Email Screenshot')
    proposal_filename = fields.Char(string='Proposal Filename', tracking=True)
    engagement_file = fields.Binary(string='Engagement Letter')
    engagement_filename = fields.Char(string='Engagement Filename', tracking=True)
    receipt_voucher_file = fields.Binary(string='Receipt Voucher')
    receipt_voucher_filename = fields.Char(string='Receipt Voucher Filename', tracking=True)

    document_warning = fields.Char(
        string='Document Warning', compute='_compute_document_warning'
    )

    # Payment details
    payment_received_datetime = fields.Datetime(string='Payment Received Date/Time', tracking=True)
    payment_reference = fields.Char(string='Payment Reference', tracking=True)
    allowed_payment_period = fields.Char(
        string='Allowed Payment Period', compute='_compute_allowed_payment_period'
    )

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', readonly=True
    )
    claim_amount = fields.Monetary(
        string='Claim Amount', currency_field='currency_id',
        compute='_compute_claim_amount', store=True, readonly=False, tracking=True,
        help='Value claimed for this upselling request. Defaults to the sale order total.'
    )

    invoice_ids = fields.One2many(
        'account.move', compute='_compute_invoice_ids',
        string='Invoices',
    )
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_invoice_ids')
    invoice_number = fields.Char(string='Invoice Number', compute='_compute_invoice_details')
    invoice_date = fields.Date(string='Invoice Date', compute='_compute_invoice_details')
    invoice_amount = fields.Monetary(
        string='Invoice Amount', currency_field='currency_id',
        compute='_compute_invoice_details'
    )

    previous_claim_ids = fields.Many2many(
        'upselling', string='Previous Upselling Claims',
        relation='upselling_previous_claim_rel',
        column1='upselling_id', column2='previous_upselling_id',
        compute='_compute_previous_claims'
    )
    previous_claim_count = fields.Integer(
        string='Previous Claim Count', compute='_compute_previous_claims'
    )

    sequence = fields.Char(
        string='Sequence Number', required=True,
        copy=False, readonly=True, default='New',
        tracking=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('review', 'Submitted for Review'),
        ('approval', 'Submitted for Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', string='Status', tracking=True)

    # Rejection details
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False, tracking=True)
    rejected_by_id = fields.Many2one(
        'res.users', string='Rejected By', readonly=True, copy=False, tracking=True
    )
    rejection_date = fields.Datetime(
        string='Rejected On', readonly=True, copy=False, tracking=True
    )

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )
    is_approver = fields.Boolean(compute='_compute_is_approver')

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('sequence', 'New') == 'New':
                vals['sequence'] = self.env['ir.sequence'].next_by_code('upselling.sequence') or 'New'
            if vals.get('sale_order_id') and not vals.get('customer_id'):
                sale_order = self.env['sale.order'].browse(vals['sale_order_id'])
                vals['customer_id'] = sale_order.partner_id.id if sale_order.partner_id else False
            self._check_payment_period(vals.get('payment_received_datetime'))
            self._check_documents_in_vals(vals)
        records = super().create(vals_list)
        for record in records:
            record._log_document_changes({
                field: True for field, _fname, _label in REQUIRED_DOCUMENTS
                if record[field]
            })
        return records

    def write(self, vals):
        if 'sale_order_id' in vals:
            sale_order = self.env['sale.order'].browse(vals['sale_order_id'])
            vals['customer_id'] = sale_order.partner_id.id if sale_order.partner_id else False
        self._check_documents_in_vals(vals)
        if 'payment_received_datetime' in vals:
            for rec in self:
                # Only re-validate when the value actually changes, so an existing
                # request does not become unsaveable once the month rolls over.
                if rec.payment_received_datetime != fields.Datetime.to_datetime(
                    vals['payment_received_datetime']
                ):
                    rec._check_payment_period(vals['payment_received_datetime'])
        res = super().write(vals)
        uploaded = {
            field: True for field, _fname, _label in REQUIRED_DOCUMENTS
            if vals.get(field)
        }
        if uploaded:
            for rec in self:
                rec._log_document_changes(uploaded)
        return res

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('company_id')
    def _compute_is_approver(self):
        current_user = self.env.user
        for rec in self:
            company_approver = rec.company_id.approver_user_id
            rec.is_approver = bool(company_approver and company_approver.id == current_user.id)

    @api.depends('proposal_file', 'engagement_file', 'receipt_voucher_file')
    def _compute_document_warning(self):
        for rec in self:
            missing = rec._missing_documents()
            rec.document_warning = _(
                'Missing mandatory documents: %s. The request cannot be submitted until '
                'every document is uploaded.'
            ) % ', '.join(missing) if missing else False

    @api.depends_context('tz')
    def _compute_allowed_payment_period(self):
        start, end = self._get_allowed_payment_period()
        label = _(
            'Only payments received between %(start)s and %(end)s '
            '(the last completed claim cycle) are accepted.'
        ) % {
            'start': fields.Date.to_string(start),
            'end': fields.Date.to_string(end),
        }
        for rec in self:
            rec.allowed_payment_period = label

    @api.depends('sale_order_id')
    def _compute_invoice_ids(self):
        for rec in self:
            if rec.sale_order_id:
                invoices = rec.sale_order_id.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice'
                )
                rec.invoice_ids = invoices
                rec.invoice_count = len(invoices)
            else:
                rec.invoice_ids = False
                rec.invoice_count = 0

    @api.depends('invoice_ids', 'invoice_ids.name', 'invoice_ids.invoice_date',
                 'invoice_ids.amount_total_signed')
    def _compute_invoice_details(self):
        for rec in self:
            invoices = rec.invoice_ids
            # Draft moves have no name yet, fall back to a readable placeholder.
            names = [inv.name or _('Draft Invoice') for inv in invoices]
            rec.invoice_number = ', '.join(names) if names else False
            invoice_dates = [d for d in invoices.mapped('invoice_date') if d]
            rec.invoice_date = max(invoice_dates) if invoice_dates else False
            rec.invoice_amount = sum(invoices.mapped('amount_total_signed'))

    @api.depends('sale_order_id', 'sale_order_id.amount_total', 'company_id')
    def _compute_claim_amount(self):
        for rec in self:
            order = rec.sale_order_id
            if not order:
                rec.claim_amount = 0.0
                continue
            target = rec.currency_id or rec.company_id.currency_id
            if order.currency_id and target and order.currency_id != target:
                rec.claim_amount = order.currency_id._convert(
                    order.amount_total, target, rec.company_id or self.env.company,
                    fields.Date.to_date(order.date_order) or fields.Date.context_today(rec),
                )
            else:
                rec.claim_amount = order.amount_total

    @api.depends('customer_id')
    def _compute_previous_claims(self):
        for rec in self:
            if not rec.customer_id:
                rec.previous_claim_ids = False
                rec.previous_claim_count = 0
                continue
            domain = [('customer_id', '=', rec.customer_id.id)]
            origin_id = rec._origin.id
            if origin_id:
                domain.append(('id', '!=', origin_id))
            claims = self.with_context(active_test=False).search(domain, order='id desc')
            rec.previous_claim_ids = claims
            rec.previous_claim_count = len(claims)

    # ------------------------------------------------------------------
    # Onchange (frontend validation)
    # ------------------------------------------------------------------
    @api.onchange('sale_order_id')
    def _onchange_sale_order_id(self):
        if self.sale_order_id and self.sale_order_id.partner_id:
            self.customer_id = self.sale_order_id.partner_id.id
        else:
            self.customer_id = False

    @api.onchange('payment_received_datetime')
    def _onchange_payment_received_datetime(self):
        if not self.payment_received_datetime:
            return
        start, end = self._get_allowed_payment_period()
        local_date = self._payment_local_date(self.payment_received_datetime)
        if not (start <= local_date <= end):
            payment_dt = self.payment_received_datetime
            self.payment_received_datetime = False
            return {
                'warning': {
                    'title': _('Invalid Payment Period'),
                    'message': self._invalid_payment_period_message(payment_dt, start, end),
                }
            }

    @api.onchange('proposal_file', 'engagement_file', 'receipt_voucher_file')
    def _onchange_documents(self):
        """Validate format/size as soon as the file is picked, before saving."""
        for field, filename_field, label in REQUIRED_DOCUMENTS:
            data = self[field]
            if not data:
                continue
            try:
                self._validate_document(label, self[filename_field], data)
            except ValidationError as error:
                self[field] = False
                self[filename_field] = False
                return {'warning': {'title': _('Invalid Document'), 'message': error.args[0]}}

    # ------------------------------------------------------------------
    # Payment period helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_cycle_start_day(self):
        """Day of month a claim cycle opens on. Clamped to 1-28 so every month has it."""
        try:
            day = int(self.env['ir.config_parameter'].sudo().get_param(
                'refund_management_rk.upselling_cycle_start_day', DEFAULT_CYCLE_START_DAY
            ))
        except (TypeError, ValueError):
            day = DEFAULT_CYCLE_START_DAY
        return min(max(day, 1), 28)

    def _get_cycle_start(self, day_in_cycle):
        """First day of the claim cycle that contains ``day_in_cycle``."""
        start_day = self._get_cycle_start_day()
        if day_in_cycle.day >= start_day:
            return day_in_cycle.replace(day=start_day)
        return (day_in_cycle - relativedelta(months=1)).replace(day=start_day)

    def _get_allowed_payment_period(self):
        """Return (first_day, last_day) of the most recent *closed* claim cycle.

        Cycles run from the configured start day to the day before it in the
        following month (25th -> 24th by default). The cycle containing today is
        still open, so the one before it is the only claimable period.
        """
        current_cycle_start = self._get_cycle_start(fields.Date.context_today(self))
        return (
            current_cycle_start - relativedelta(months=1),
            current_cycle_start - relativedelta(days=1),
        )

    def _payment_local_date(self, payment_dt):
        """Convert a stored (UTC) datetime to a date in the user's timezone."""
        payment_dt = fields.Datetime.to_datetime(payment_dt)
        return fields.Datetime.context_timestamp(self, payment_dt).date()

    def _invalid_payment_period_message(self, payment_dt, start, end):
        return _(
            'A Payment Received Request can only be raised for the last completed '
            'claim cycle.\n\n'
            'Allowed period: %(start)s to %(end)s\n'
            'Selected date: %(selected)s\n\n'
            'Payments dated in the cycle currently running, or in any earlier cycle, '
            'cannot be submitted.'
        ) % {
            'start': fields.Date.to_string(start),
            'end': fields.Date.to_string(end),
            'selected': fields.Date.to_string(self._payment_local_date(payment_dt)),
        }

    def _check_payment_period(self, payment_dt):
        """Backend/API level guard for the claim-cycle payment restriction."""
        if not payment_dt:
            return
        start, end = self._get_allowed_payment_period()
        local_date = self._payment_local_date(payment_dt)
        if not (start <= local_date <= end):
            raise ValidationError(self._invalid_payment_period_message(payment_dt, start, end))

    # ------------------------------------------------------------------
    # Document helpers
    # ------------------------------------------------------------------
    def _missing_documents(self):
        self.ensure_one()
        return [label for field, _fname, label in REQUIRED_DOCUMENTS if not self[field]]

    @api.model
    def _get_allowed_extensions(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'refund_management_rk.upselling_allowed_extensions', DEFAULT_ALLOWED_EXTENSIONS
        )
        return [ext.strip().lower().lstrip('.') for ext in (param or '').split(',') if ext.strip()]

    @api.model
    def _get_max_file_size(self):
        """Max upload size in bytes, capped by the instance-wide web limit."""
        config = self.env['ir.config_parameter'].sudo()
        try:
            max_mb = float(config.get_param(
                'refund_management_rk.upselling_max_file_size_mb', DEFAULT_MAX_FILE_SIZE_MB
            ))
        except (TypeError, ValueError):
            max_mb = DEFAULT_MAX_FILE_SIZE_MB
        max_bytes = int(max_mb * 1024 * 1024)
        try:
            web_limit = int(config.get_param('web.max_file_upload_size', 0))
        except (TypeError, ValueError):
            web_limit = 0
        if web_limit:
            max_bytes = min(max_bytes, web_limit)
        return max_bytes

    @api.model
    def _validate_document(self, label, filename, data):
        """Raise ValidationError when a document breaks the format/size standards."""
        if not data:
            return
        allowed = self._get_allowed_extensions()
        if not filename or '.' not in filename:
            raise ValidationError(_(
                '%(label)s: the file name is missing an extension, so its format cannot be '
                'verified. Allowed formats: %(allowed)s.'
            ) % {'label': label, 'allowed': ', '.join(allowed)})
        extension = filename.rsplit('.', 1)[-1].lower()
        if allowed and extension not in allowed:
            raise ValidationError(_(
                '%(label)s: "%(filename)s" is not a supported file format.\n'
                'Allowed formats: %(allowed)s.'
            ) % {'label': label, 'filename': filename, 'allowed': ', '.join(allowed)})

        try:
            size = len(base64.b64decode(data))
        except Exception:  # noqa: BLE001 - corrupt payload, report as a size/format problem
            raise ValidationError(_(
                '%(label)s: "%(filename)s" could not be read. Please upload the file again.'
            ) % {'label': label, 'filename': filename})
        max_bytes = self._get_max_file_size()
        if max_bytes and size > max_bytes:
            raise ValidationError(_(
                '%(label)s: "%(filename)s" is %(size).2f MB, which exceeds the maximum '
                'allowed size of %(max)s MB.'
            ) % {
                'label': label, 'filename': filename,
                'size': size / (1024 * 1024), 'max': round(max_bytes / (1024 * 1024), 2),
            })

    def _check_documents_in_vals(self, vals):
        """Validate any document present in a create/write payload (UI and API)."""
        for field, filename_field, label in REQUIRED_DOCUMENTS:
            if field not in vals or not vals.get(field):
                continue
            filename = vals.get(filename_field)
            if filename is None and self:
                filename = self[:1][filename_field]
            self._validate_document(label, filename, vals[field])

    def _check_documents_complete(self):
        """Block a workflow step when a mandatory document is missing."""
        for rec in self:
            missing = rec._missing_documents()
            if missing:
                raise UserError(_(
                    'Upselling request %(sequence)s cannot be submitted.\n\n'
                    'The following mandatory documents are missing:\n- %(missing)s'
                ) % {'sequence': rec.sequence, 'missing': '\n- '.join(missing)})

    def _log_document_changes(self, uploaded):
        """Audit log entry for every document added to the request."""
        self.ensure_one()
        labels = []
        for field, filename_field, label in REQUIRED_DOCUMENTS:
            if uploaded.get(field):
                labels.append('%s (%s)' % (label, self[filename_field] or _('unnamed file')))
        if not labels:
            return
        self.message_post(
            body=Markup('<b>Document uploaded:</b><br/>%s') % Markup('<br/>').join(labels),
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )

    # ------------------------------------------------------------------
    # State transition buttons
    # ------------------------------------------------------------------
    def _check_not_rejected(self):
        for rec in self:
            if rec.state == 'rejected':
                raise UserError(_(
                    'Upselling request %s has been rejected and can no longer proceed '
                    'through the approval workflow.'
                ) % rec.sequence)

    def action_submit_review(self):
        self._check_not_rejected()
        for rec in self:
            rec._check_documents_complete()
            rec.state = 'review'
            rec.message_post(
                body=Markup(_('<b>Submitted for Review</b> by %s.')) % rec.user_id.name,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )
            # Notify all reviewers by email
            reviewer_group = self.env.ref(
                'refund_management_rk.group_reimbursement_reviewer', raise_if_not_found=False
            )
            if reviewer_group:
                partner_ids = reviewer_group.users.mapped('partner_id').ids
                if partner_ids:
                    rec.message_notify(
                        partner_ids=partner_ids,
                        subject=f'Upselling {rec.sequence} - Submitted for Review',
                        body=Markup(
                            'Dear Reviewer,<br/><br/>'
                            'Upselling request <b>{}</b> has been submitted for review by {}.<br/><br/>'
                            'Please review and take action.'
                        ).format(rec.sequence, rec.user_id.name),
                    )

    def action_submit_approval(self):
        self.ensure_one()
        self._check_not_rejected()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submit for Approval',
            'res_model': 'upselling.approval.remark.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_upselling_id': self.id},
        }

    def action_approve(self):
        self._check_not_rejected()
        for rec in self:
            if not rec.is_approver:
                raise UserError("You are not authorized to approve this upselling request.")
            rec._check_documents_complete()
            rec.state = 'approved'
            rec.message_post(
                body=Markup(_('<b>Approved</b> by %s.')) % self.env.user.name,
                message_type='notification',
                subtype_xmlid='mail.mt_note',
            )

    def action_reject(self):
        self.ensure_one()
        if self.state not in ('review', 'approval'):
            raise UserError(_(
                'Only requests submitted for review or approval can be rejected.'
            ))
        self._check_reject_authorisation()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Upselling',
            'res_model': 'upselling.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_upselling_id': self.id},
        }

    def _check_reject_authorisation(self):
        """Reviewers reject at review stage, the approver at approval stage."""
        self.ensure_one()
        user = self.env.user
        if self.state == 'review':
            if not user.has_group('refund_management_rk.group_reimbursement_reviewer'):
                raise UserError(_('Only Reimbursement Reviewers can reject a request under review.'))
        elif self.state == 'approval':
            if not (self.is_approver or user.has_group('refund_management_rk.group_reimbursement_approver')):
                raise UserError(_(
                    'Only the Reimbursement Approver can reject a request submitted for approval.'
                ))

    def action_resubmit(self):
        self.ensure_one()
        if not self.env.user.has_group('refund_management_rk.group_reimbursement_reviewer'):
            raise UserError("Only Reimbursement Reviewers can request a resubmission.")
        self._check_not_rejected()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Request Resubmission',
            'res_model': 'upselling.resubmit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_upselling_id': self.id},
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoices',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }

    def action_view_previous_claims(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Previous Upselling Claims - %s') % (self.customer_id.display_name or ''),
            'res_model': 'upselling',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.previous_claim_ids.ids)],
        }
