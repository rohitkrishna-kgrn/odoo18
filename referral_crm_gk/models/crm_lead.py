import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    x_is_referral = fields.Boolean(
        string='Is Referral',
        default=False,
        index=True,
    )
    x_referral_company = fields.Char(string='Referred Company')
    x_referrer_id = fields.Many2one(
        'referral.referrer',
        string='Referrer',
        ondelete='set null',
        index=True,
    )
    x_referral_ref = fields.Char(
        string='Referral Reference',
        index=True,
        copy=False,
        readonly=True,
    )
    # ── Invoice integration ────────────────────────────────────────────────
    x_invoice_id = fields.Many2one(
        'account.move',
        string='Linked Invoice',
        domain=[('move_type', '=', 'out_invoice')],
        copy=False,
        readonly=True,
        ondelete='set null',
        index=True,
    )
    x_invoice_number = fields.Char(
        related='x_invoice_id.name',
        string='Invoice Number',
        readonly=True,
    )
    x_invoice_date = fields.Date(
        related='x_invoice_id.invoice_date',
        string='Invoice Date',
        readonly=True,
    )
    x_invoice_amount_total = fields.Monetary(
        related='x_invoice_id.amount_total',
        string='Invoice Total (AED)',
        readonly=True,
        currency_field='company_currency',
    )
    x_invoice_amount_residual = fields.Monetary(
        related='x_invoice_id.amount_residual',
        string='Outstanding Amount (AED)',
        readonly=True,
        currency_field='company_currency',
    )
    x_invoice_payment_state = fields.Selection(
        related='x_invoice_id.payment_state',
        string='Invoice Payment Status',
        readonly=True,
    )
    x_invoice_state = fields.Selection(
        related='x_invoice_id.state',
        string='Invoice State',
        readonly=True,
    )
    x_invoice_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_invoice_attachments',
        string='Invoice Documents',
    )

    # Billing/payment stage — drives the visible statusbar on the referral form
    x_billing_stage = fields.Selection([
        ('no_invoice', 'No Invoice'),
        ('invoice_draft', 'Invoice Draft'),
        ('not_paid', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
    ], string='Payment Stage',
       compute='_compute_billing_stage',
       store=True,
    )

    # Commission payment status — computed from invoice when linked; manual otherwise
    x_payment_status = fields.Selection([
        ('pending', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('full', 'Fully Paid'),
    ], string='Commission Payment Status',
       compute='_compute_payment_status',
       inverse='_set_payment_status',
       store=True,
       readonly=False,
    )

    x_sale_order_id = fields.Many2one(
        'sale.order',
        string='Linked Quotation',
        copy=False,
        readonly=True,
    )
    x_deal_value = fields.Float(
        string='Deal Value (AED)',
        compute='_compute_deal_value',
        store=True,
        digits=(16, 2),
    )
    x_has_quotation = fields.Boolean(
        string='Has Quotation',
        compute='_compute_has_quotation',
    )

    x_commission_rate = fields.Float(
        related='x_referrer_id.commission_rate',
        string='Commission Rate (%)',
        store=True,
        readonly=True,
        digits=(5, 2),
    )
    x_referrer_company_name = fields.Char(
        related='x_referrer_id.company', string='Referrer Company', readonly=True,
    )
    x_referrer_email = fields.Char(
        related='x_referrer_id.email', string='Referrer Email', readonly=True,
    )
    x_referrer_phone = fields.Char(
        related='x_referrer_id.phone', string='Referrer Phone', readonly=True,
    )
    x_referrer_tier = fields.Selection(
        related='x_referrer_id.tier', string='Referrer Tier', readonly=True,
    )
    x_referrer_conversions = fields.Integer(
        related='x_referrer_id.total_conversions',
        string='Referrer Total Conversions', readonly=True,
    )
    x_commission_amount = fields.Float(
        compute='_compute_commission',
        store=True,
        string='Commission Amount (AED)',
        digits=(16, 2),
    )
    x_referrer_total_commission = fields.Float(
        related='x_referrer_id.total_commission_earned',
        string='Total Commission Earned (AED)',
        readonly=True,
        digits=(16, 2),
    )
    x_stage_color_hex = fields.Char(
        related='stage_id.x_color_hex',
        string='Stage Colour',
        readonly=True,
    )
    x_stage_name = fields.Char(
        related='stage_id.name',
        string='Stage Name',
        readonly=True,
    )
    x_stage_is_converted = fields.Boolean(
        related='stage_id.x_is_referral_converted',
        string='Stage Is Converted',
        readonly=True,
    )
    x_stage_is_lost = fields.Boolean(
        related='stage_id.x_is_referral_lost',
        string='Stage Is Lost',
        readonly=True,
    )
    x_commission_id = fields.Many2one(
        'referral.commission',
        compute='_compute_commission_id',
        string='Commission',
    )
    x_stage_entry_criteria = fields.Char(
        related='stage_id.x_entry_criteria',
        string='Entry Criteria',
        readonly=True,
    )
    x_stage_guidance = fields.Text(
        related='stage_id.x_stage_description',
        string='Stage Guidance',
        readonly=True,
    )

    @api.depends('x_sale_order_id', 'x_sale_order_id.amount_untaxed')
    def _compute_deal_value(self):
        # Use untaxed amount so commissions are calculated on the net service fee, not on VAT
        for rec in self:
            rec.x_deal_value = rec.x_sale_order_id.amount_untaxed if rec.x_sale_order_id else 0.0

    @api.depends('x_sale_order_id')
    def _compute_has_quotation(self):
        for rec in self:
            rec.x_has_quotation = bool(rec.x_sale_order_id)

    @api.depends('x_deal_value', 'x_referrer_id.commission_rate', 'x_is_referral')
    def _compute_commission(self):
        for rec in self:
            if rec.x_is_referral and rec.x_referrer_id and rec.x_deal_value:
                rec.x_commission_amount = rec.x_deal_value * rec.x_referrer_id.commission_rate / 100.0
            else:
                rec.x_commission_amount = 0.0

    def _compute_commission_id(self):
        commissions = self.env['referral.commission'].search([('lead_id', 'in', self.ids)])
        commission_map = {c.lead_id.id: c for c in commissions}
        for rec in self:
            rec.x_commission_id = commission_map.get(rec.id)

    _INVOICE_PAYMENT_STATE_MAP = {
        'not_paid': 'pending',
        'partial': 'partial',
        'in_payment': 'partial',
        'paid': 'full',
        'reversed': 'pending',
        'invoicing_legacy': 'pending',
    }

    @api.depends('x_invoice_id', 'x_invoice_id.payment_state')
    def _compute_payment_status(self):
        for rec in self:
            if rec.x_invoice_id:
                rec.x_payment_status = self._INVOICE_PAYMENT_STATE_MAP.get(
                    rec.x_invoice_id.payment_state, 'pending'
                )
            else:
                rec.x_payment_status = 'pending'

    def _set_payment_status(self):
        # Allows manual writes for leads without a linked invoice.
        # When an invoice is linked the compute overrides any manual value.
        pass

    @api.depends(
        'x_invoice_id',
        'x_invoice_id.state',
        'x_invoice_id.payment_state',
    )
    def _compute_billing_stage(self):
        for rec in self:
            inv = rec.x_invoice_id
            if not inv:
                rec.x_billing_stage = 'no_invoice'
            elif inv.state == 'draft':
                rec.x_billing_stage = 'invoice_draft'
            elif inv.payment_state in ('not_paid', 'invoicing_legacy', 'reversed'):
                rec.x_billing_stage = 'not_paid'
            elif inv.payment_state in ('partial', 'in_payment'):
                rec.x_billing_stage = 'partial'
            elif inv.payment_state == 'paid':
                rec.x_billing_stage = 'paid'
            else:
                rec.x_billing_stage = 'not_paid'

    @api.depends('x_invoice_id')
    def _compute_invoice_attachments(self):
        Attachment = self.env['ir.attachment'].sudo()
        for rec in self:
            if not rec.x_invoice_id:
                rec.x_invoice_attachment_ids = Attachment.browse()
                continue
            # Attachments on the invoice itself
            invoice_attachment_ids = Attachment.search([
                ('res_model', '=', 'account.move'),
                ('res_id', '=', rec.x_invoice_id.id),
            ])
            # Attachments on reconciled payment journal entries
            try:
                rcv_lines = rec.x_invoice_id.line_ids.filtered(
                    lambda l: l.account_id.account_type in (
                        'asset_receivable', 'liability_payable'
                    ) and l.reconciled
                )
                payment_move_ids = (
                    rcv_lines.mapped('matched_debit_ids.debit_move_id.id')
                    + rcv_lines.mapped('matched_credit_ids.credit_move_id.id')
                )
                if payment_move_ids:
                    payment_attachment_ids = Attachment.search([
                        ('res_model', '=', 'account.move'),
                        ('res_id', 'in', payment_move_ids),
                    ])
                    rec.x_invoice_attachment_ids = invoice_attachment_ids | payment_attachment_ids
                else:
                    rec.x_invoice_attachment_ids = invoice_attachment_ids
            except Exception:
                rec.x_invoice_attachment_ids = invoice_attachment_ids

    # ── Invoice actions ───────────────────────────────────────────────────

    def action_open_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.x_invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_create_invoice(self):
        """Create invoice from the linked sale order and open it."""
        self.ensure_one()
        from odoo.exceptions import UserError
        if not self.x_sale_order_id:
            raise UserError(
                "No sale order is linked to this referral. "
                "Please create a quotation first."
            )
        if self.x_sale_order_id.state not in ('sale', 'done'):
            raise UserError(
                "The sale order must be confirmed before creating an invoice."
            )
        # If invoice already exists, just open it
        if self.x_invoice_id:
            return self.action_open_invoice()
        # Create the invoice — our _create_invoices override auto-links it
        self.x_sale_order_id.sudo()._create_invoices()
        # Fallback link in case override didn't fire
        if not self.x_invoice_id:
            existing = self.x_sale_order_id.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )
            if existing:
                self.sudo().x_invoice_id = existing[0].id
        if self.sudo().x_invoice_id:
            return self.action_open_invoice()
        raise UserError("Invoice could not be created. Please try from the Sales Order.")

    def action_register_payment(self):
        """Open the standard Odoo payment registration wizard for the linked invoice."""
        self.ensure_one()
        from odoo.exceptions import UserError
        if not self.x_invoice_id:
            raise UserError("No invoice is linked to this referral.")
        if self.x_invoice_id.state != 'posted':
            raise UserError(
                "The invoice must be confirmed (posted) before registering a payment."
            )
        if self.x_invoice_id.payment_state == 'paid':
            raise UserError("This invoice is already fully paid.")
        return self.x_invoice_id.action_register_payment()

    # ── Email notifications ────────────────────────────────────────────────

    def _send_template_email(self, template_xml_id, extra_recipients=None, email_to=None):
        template = self.env.ref(
            f'referral_crm_gk.{template_xml_id}', raise_if_not_found=False
        )
        if not template:
            _logger.warning('referral_crm_gk: template %s not found', template_xml_id)
            return
        email_values = {'auto_delete': False}
        if email_to:
            email_values.update({'email_to': email_to, 'recipient_ids': []})
        elif extra_recipients:
            partners = extra_recipients.filtered('email')
            if not partners:
                _logger.warning(
                    'referral_crm_gk: no email recipients for template %s', template_xml_id
                )
                return
            email_values.update({
                'recipient_ids': [(4, p.id) for p in partners],
                'email_to': '',
            })
        template.send_mail(
            self.id,
            force_send=True,
            raise_exception=False,
            email_values=email_values,
        )

    def _get_referral_manager_partners(self):
        group = self.env.ref('referral_crm_gk.group_referral_manager', raise_if_not_found=False)
        if not group:
            return self.env['res.partner'].browse()
        system_user = self.env.ref('base.user_root', raise_if_not_found=False)
        managers = group.users.filtered(
            lambda u: u.active and not u.share and u != system_user
        )
        return managers.mapped('partner_id').filtered('email')

    def _notify_managers_new_referral(self):
        self.ensure_one()
        manager_partners = self._get_referral_manager_partners()
        if not manager_partners:
            return
        self._send_template_email(
            'email_template_referral_new_manager', extra_recipients=manager_partners
        )

    def _notify_salesperson_assigned(self):
        self.ensure_one()
        if not self.user_id or not self.user_id.partner_id.email:
            return
        self._send_template_email(
            'email_template_referral_salesperson',
            extra_recipients=self.user_id.partner_id,
        )

    def _notify_managers_converted(self):
        self.ensure_one()
        manager_partners = self._get_referral_manager_partners()
        if not manager_partners:
            return
        self._send_template_email(
            'email_template_referral_converted', extra_recipients=manager_partners
        )

    # ── ORM overrides ─────────────────────────────────────────────────────

    def write(self, vals):
        old_user_ids = {}
        if 'user_id' in vals:
            old_user_ids = {
                rec.id: rec.user_id.id
                for rec in self
                if rec.x_is_referral
            }

        result = super().write(vals)

        if 'user_id' in vals:
            for rec in self:
                if (rec.x_is_referral and rec.user_id
                        and rec.user_id.id != old_user_ids.get(rec.id)):
                    rec.sudo()._notify_salesperson_assigned()

        if 'stage_id' in vals:
            Commission = self.env['referral.commission'].sudo()
            for rec in self:
                if rec.x_is_referral and rec.stage_id.x_is_referral_converted:
                    if not Commission.search([('lead_id', '=', rec.id)], limit=1):
                        Commission.create({'lead_id': rec.id})
                        rec.sudo()._notify_managers_converted()

        return result

    @api.model_create_multi
    def create(self, vals_list):
        default_manager = self._get_default_referral_manager()
        first_referral_stage = None
        referral_stage_ids = None  # cached set of valid referral stage IDs
        for vals in vals_list:
            if vals.get('x_is_referral'):
                if not vals.get('user_id') and default_manager:
                    vals['user_id'] = default_manager.id
                # Ensure the stage is actually a referral stage.
                # Odoo's model default resolves stage_id before create() runs and may
                # pick a non-referral stage (first global CRM stage by sequence).
                if referral_stage_ids is None:
                    referral_stage_ids = set(
                        self.env['crm.stage'].search(
                            [('x_is_referral_stage', '=', True)]
                        ).ids
                    )
                if vals.get('stage_id') not in referral_stage_ids:
                    if first_referral_stage is None:
                        first_referral_stage = self.env['crm.stage'].search(
                            [
                                ('x_is_referral_stage', '=', True),
                                ('x_is_referral_converted', '=', False),
                                ('x_is_referral_lost', '=', False),
                            ],
                            order='sequence asc',
                            limit=1,
                        )
                    if first_referral_stage:
                        vals['stage_id'] = first_referral_stage.id
        records = super().create(vals_list)
        for rec in records:
            if rec.x_is_referral:
                if not rec.x_referral_ref:
                    rec.x_referral_ref = f'REF-{rec.id:05d}'
                if not rec.partner_id:
                    partner = rec._find_or_create_referral_partner()
                    if partner:
                        rec.partner_id = partner.id
        for rec in records:
            if rec.x_is_referral:
                rec.sudo()._notify_managers_new_referral()
        return records

    # ── Helpers ───────────────────────────────────────────────────────────

    def _compute_show_enrich_button(self):
        super()._compute_show_enrich_button()
        for lead in self:
            if lead.x_is_referral:
                lead.show_enrich_button = False

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        if self.env.context.get('default_x_is_referral'):
            return stages.search([('x_is_referral_stage', '=', True)])
        # Keep referral-only stages out of the main (non-referral) pipeline.
        return super()._read_group_stage_ids(stages, domain).filtered(
            lambda stage: not stage.x_is_referral_stage)

    @api.model
    def _get_default_referral_manager(self):
        group = self.env.ref('referral_crm_gk.group_referral_manager', raise_if_not_found=False)
        if not group:
            return self.env['res.users'].browse()
        system_user = self.env.ref('base.user_root', raise_if_not_found=False)
        managers = group.users.filtered(
            lambda u: u.active and not u.share and u != system_user
        )
        return managers[0] if managers else self.env['res.users'].browse()

    def _find_or_create_referral_partner(self):
        self.ensure_one()
        Partner = self.env['res.partner']

        # 1. Deduplicate by email — any existing partner with this email wins,
        #    regardless of company name supplied in the form.
        if self.email_from:
            partner = Partner.search(
                [('email', '=ilike', self.email_from)], limit=1
            )
            if partner:
                return partner

        # 2. Fall back to company-name match.
        company_name = self.x_referral_company
        if not company_name and self.name:
            m = re.search(r'\(([^)]+)\)\s*$', self.name)
            if m:
                company_name = m.group(1)
        if not company_name:
            return Partner.browse()

        partner = Partner.search(
            [('name', '=ilike', company_name), ('is_company', '=', True)],
            limit=1,
        )
        if not partner:
            partner = Partner.create({
                'name': company_name,
                'is_company': True,
            })
        return partner

    def _get_referral_stage(self, name_ilike):
        return self.env['crm.stage'].search(
            [('x_is_referral_stage', '=', True), ('name', 'ilike', name_ilike)],
            order='sequence', limit=1,
        )

    # ── Stage actions ─────────────────────────────────────────────────────

    def action_move_to_contacted(self):
        self.ensure_one()
        stage = self._get_referral_stage('Contacted')
        if stage:
            self.stage_id = stage.id
        return True

    def action_move_to_not_qualified(self):
        self.ensure_one()
        stage = self._get_referral_stage('Not Qualified')
        if stage:
            self.stage_id = stage.id
        return True

    def action_next_stage(self):
        self.ensure_one()
        active_stages = self.env['crm.stage'].search(
            [('x_is_referral_stage', '=', True), ('x_is_referral_lost', '=', False)],
            order='sequence',
        )
        stage_ids = active_stages.ids
        if self.stage_id.id in stage_ids:
            idx = stage_ids.index(self.stage_id.id)
            if idx + 1 < len(stage_ids):
                self.stage_id = active_stages[idx + 1]
        return True

    # ── Quotation actions ─────────────────────────────────────────────────

    def action_create_quotation(self):
        self.ensure_one()
        if self.x_sale_order_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': self.x_sale_order_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        partner = self.partner_id or self._find_or_create_referral_partner()
        if partner and not self.partner_id:
            self.partner_id = partner.id
        so = self.env['sale.order'].create({
            'partner_id': partner.id if partner else self.env.ref('base.res_partner_1').id,
            'x_referral_lead_id': self.id,
            'client_order_ref': self.x_referral_ref or self.name,
        })
        self.x_sale_order_id = so.id

        # Auto-create order lines from referral service tags
        if self.tag_ids:
            ProductProduct = self.env['product.product'].sudo()
            order_lines = []
            today = fields.Date.today()
            line_manager_id = (self.user_id or self.env.user).id
            for tag in self.tag_ids:
                product = ProductProduct.search(
                    [('name', '=', tag.name), ('type', '=', 'service')], limit=1
                )
                if not product:
                    product = ProductProduct.create({
                        'name': tag.name,
                        'type': 'service',
                        'invoice_policy': 'order',
                    })
                order_lines.append((0, 0, {
                    'product_id': product.id,
                    'product_uom_qty': 1,
                    'price_unit': 0.0,
                    'name': tag.name,
                    'manager_id': line_manager_id,
                    'engagement_start': today,
                    'engagement_end': today,
                    'deadline': today,
                    'estimated_hours': product.sudo().product_tmpl_id.estimated_hours or 0.0,
                }))
            if order_lines:
                so.sudo().write({'order_line': order_lines})

        stage = self._get_referral_stage('In Progress')
        if stage:
            self.stage_id = stage.id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': so.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_quotation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.x_sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_commission(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'referral.commission',
            'res_id': self.x_commission_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
