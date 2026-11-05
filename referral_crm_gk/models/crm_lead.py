import logging
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    x_is_referral = fields.Boolean(
        string='Is Referral',
        default=False,
        index=True,
    )
    x_referral_company = fields.Char(string='Referred Company')
    # What the referrer ticked on the portal. Kept out of tag_ids: CRM tags
    # classify where a lead came from (this one: REF BY CONSULTANT), and
    # they sync onto the contact.
    x_referral_services = fields.Char(string='Services of Interest')
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
    # Follows the referrer's tier rate until a Referral Manager edits it on the
    # lead; from then on x_commission_rate_manual pins the edited value.
    x_commission_rate = fields.Float(
        compute='_compute_commission_rate',
        string='Commission Rate (%)',
        store=True,
        readonly=False,
        tracking=True,
        digits=(5, 2),
    )
    x_commission_rate_manual = fields.Boolean(
        string='Commission Rate Edited',
        copy=False,
    )
    x_can_edit_commission_rate = fields.Boolean(
        compute='_compute_can_edit_commission_rate',
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
    # Converted = Won, which crm_extended_rk sets when the quotation is
    # confirmed; lost = its Lost or Not Qualified column.
    x_stage_is_converted = fields.Boolean(
        related='stage_id.is_won',
        string='Stage Is Converted',
        readonly=True,
    )
    x_stage_is_lost = fields.Boolean(
        compute='_compute_stage_is_lost',
        search='_search_stage_is_lost',
        string='Stage Is Lost',
    )
    x_commission_id = fields.Many2one(
        'referral.commission',
        compute='_compute_commission_id',
        string='Commission',
    )
    @api.depends('x_sale_order_id', 'x_sale_order_id.amount_untaxed')
    def _compute_deal_value(self):
        # Use untaxed amount so commissions are calculated on the net service fee, not on VAT
        for rec in self:
            rec.x_deal_value = rec.x_sale_order_id.amount_untaxed if rec.x_sale_order_id else 0.0

    @api.model
    def _get_referral_views(self, modes=('list', 'kanban', 'form')):
        """(view_id, mode) pairs for the Referral screens: they have no New button."""
        xmlids = {
            'list': 'referral_crm_gk.view_referral_lead_list',
            'kanban': 'referral_crm_gk.view_referral_lead_kanban',
            'form': 'referral_crm_gk.view_referral_lead_form',
        }
        return [(self.env.ref(xmlids[m]).id, m) for m in modes]

    @api.model
    def _get_referral_lost_stages(self):
        stages = self.env['crm.stage']
        for xmlid in ('crm_extended_rk.stage_lost', 'crm_extended_rk.stage_not_qualified'):
            stages |= self.env.ref(xmlid, raise_if_not_found=False) or stages
        return stages

    @api.depends('stage_id')
    def _compute_stage_is_lost(self):
        lost_stages = self._get_referral_lost_stages()
        for rec in self:
            rec.x_stage_is_lost = rec.stage_id in lost_stages

    def _search_stage_is_lost(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError()
        positive = (operator == '=') == value
        return [('stage_id', 'in' if positive else 'not in', self._get_referral_lost_stages().ids)]

    @api.depends('x_referrer_id.commission_rate')
    def _compute_commission_rate(self):
        for rec in self:
            # Records left unassigned keep their stored (manually edited) rate
            if not rec.x_commission_rate_manual:
                rec.x_commission_rate = rec.x_referrer_id.commission_rate

    @api.depends_context('uid')
    def _compute_can_edit_commission_rate(self):
        can_edit = self.env.user.has_group('referral_crm_gk.group_referral_manager')
        for rec in self:
            rec.x_can_edit_commission_rate = can_edit

    @api.depends('x_deal_value', 'x_commission_rate', 'x_is_referral')
    def _compute_commission(self):
        for rec in self:
            if rec.x_is_referral and rec.x_referrer_id and rec.x_deal_value:
                rec.x_commission_amount = rec.x_deal_value * rec.x_commission_rate / 100.0
            else:
                rec.x_commission_amount = 0.0

    def _compute_commission_id(self):
        # sudo: this only feeds the smart button; any CRM user opening a lead
        # computes it, and most of them have no Referral group (ACL error).
        # Opening the commission itself still goes through the normal ACL.
        commissions = self.env['referral.commission'].sudo().search([('lead_id', 'in', self.ids)])
        commission_map = {c.lead_id.id: c for c in commissions}
        for rec in self:
            rec.x_commission_id = commission_map.get(rec.id)

    # in_payment = the customer has paid in full and only the bank
    # reconciliation is outstanding, so it counts as paid here.
    _INVOICE_PAYMENT_STATE_MAP = {
        'not_paid': 'pending',
        'partial': 'partial',
        'in_payment': 'full',
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
            elif inv.payment_state == 'partial':
                rec.x_billing_stage = 'partial'
            elif inv.payment_state in ('in_payment', 'paid'):
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
        # user_notification keeps the mail linked to the lead (Settings >
        # Emails) but out of its chatter, where the full HTML email was
        # being pasted as a message.
        email_values = {'auto_delete': False, 'message_type': 'user_notification'}
        if email_to:
            email_values.update({'email_to': email_to, 'recipient_ids': []})
        elif extra_recipients:
            # Referral Admins never receive mail from this module
            partners = extra_recipients.filtered('email') - self._get_referral_admin_partners()
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

    @api.model
    def _get_referral_admin_partners(self):
        group = self.env.ref('referral_crm_gk.group_referral_admin', raise_if_not_found=False)
        if not group:
            return self.env['res.partner'].browse()
        return group.sudo().users.mapped('partner_id')

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
        if 'x_commission_rate' in vals:
            if not (self.env.su or self.env.user.has_group('referral_crm_gk.group_referral_manager')):
                raise AccessError("Only a Referral Manager can change the commission rate.")
            if self.env['referral.commission'].sudo().search_count([
                ('lead_id', 'in', self.ids), ('commission_payment_status', '=', 'paid'),
            ]):
                raise UserError(
                    "The commission for this referral has already been paid, "
                    "so its commission rate can no longer be changed."
                )
            vals = dict(vals, x_commission_rate_manual=True)

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
                if rec.x_is_referral and rec.stage_id.is_won:
                    if not Commission.search([('lead_id', '=', rec.id)], limit=1):
                        Commission.create({'lead_id': rec.id})
                        rec.sudo()._notify_managers_converted()

        return result

    @api.model_create_multi
    def create(self, vals_list):
        default_manager = self._get_default_referral_manager()
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        ref_tag = self.env.ref(
            'crm_extended_rk.quotation_tag_ref_by_consultant', raise_if_not_found=False)
        for vals in vals_list:
            if vals.get('x_is_referral'):
                if not vals.get('user_id') and default_manager:
                    vals['user_id'] = default_manager.id
                # The CRM pipeline only shows opportunities, and only an
                # opportunity gets the New Quotation button.
                vals.setdefault('type', 'opportunity')
                if not vals.get('stage_id') and new_stage:
                    vals['stage_id'] = new_stage.id
                if ref_tag:
                    vals['tag_ids'] = list(vals.get('tag_ids') or []) + [(4, ref_tag.id)]
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
    def _get_default_referral_manager(self):
        group = self.env.ref('referral_crm_gk.group_referral_manager', raise_if_not_found=False)
        if not group:
            return self.env['res.users'].browse()
        system_user = self.env.ref('base.user_root', raise_if_not_found=False)
        admin_users = self._get_referral_admin_partners().user_ids
        managers = group.users.filtered(
            lambda u: u.active and not u.share and u != system_user
            and u not in admin_users
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

    def action_view_commission(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'referral.commission',
            'res_id': self.x_commission_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
