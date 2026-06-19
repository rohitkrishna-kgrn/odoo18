import re

from odoo import api, fields, models


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
    x_payment_status = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('full', 'Full'),
    ], string='Payment Status', default='pending')

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

    @api.depends('x_sale_order_id', 'x_sale_order_id.amount_total')
    def _compute_deal_value(self):
        for rec in self:
            rec.x_deal_value = rec.x_sale_order_id.amount_total if rec.x_sale_order_id else 0.0

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

    # ── Email notifications ────────────────────────────────────────────────

    def _send_notification_email(self, subject, body_html, partner_ids):
        """Send a notification email via mail.mail (no chatter, no user signature)."""
        if not partner_ids:
            return
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body_html,
            'recipient_ids': [(6, 0, partner_ids)],
            'auto_delete': True,
        }).send()

    def _get_referral_manager_partners(self):
        """Return partner records for all active referral managers who have an email."""
        group = self.env.ref('referral_crm_gk.group_referral_manager', raise_if_not_found=False)
        if not group:
            return self.env['res.partner'].browse()
        system_user = self.env.ref('base.user_root', raise_if_not_found=False)
        managers = group.users.filtered(
            lambda u: u.active and not u.share and u != system_user
        )
        return managers.mapped('partner_id').filtered('email')

    def _notify_managers_new_referral(self):
        """Email managers when a new referral is submitted."""
        self.ensure_one()
        manager_partners = self._get_referral_manager_partners()
        if not manager_partners:
            return
        referrer = self.x_referrer_id
        referrer_label = referrer.name if referrer else '—'
        if referrer and referrer.company:
            referrer_label += f' ({referrer.company})'
        body = f"""
            <p>A new referral has been submitted and requires your attention.</p>
            <table style="border-collapse:collapse;width:100%;max-width:520px;font-size:14px">
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold;width:170px">Reference</td>
                    <td style="padding:6px 10px">{self.x_referral_ref or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referrer</td>
                    <td style="padding:6px 10px">{referrer_label}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referrer Email</td>
                    <td style="padding:6px 10px">{referrer.email if referrer else '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referrer Phone</td>
                    <td style="padding:6px 10px">{referrer.phone if referrer else '—'}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referred Contact</td>
                    <td style="padding:6px 10px">{self.partner_name or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referred Company</td>
                    <td style="padding:6px 10px">{self.x_referral_company or '—'}</td>
                </tr>
            </table>
            <p style="margin-top:12px">Please review and assign to a salesperson.</p>
        """
        self._send_notification_email(
            subject=f'New Referral Submitted: {self.x_referral_ref or self.name}',
            body_html=body,
            partner_ids=manager_partners.ids,
        )

    def _notify_salesperson_assigned(self):
        """Email the salesperson when they are assigned to a referral."""
        self.ensure_one()
        if not self.user_id or not self.user_id.partner_id.email:
            return
        referrer = self.x_referrer_id
        referrer_label = referrer.name if referrer else '—'
        if referrer and referrer.company:
            referrer_label += f' ({referrer.company})'
        body = f"""
            <p>Dear {self.user_id.name},</p>
            <p>A referral has been assigned to you. Please follow up promptly.</p>
            <table style="border-collapse:collapse;width:100%;max-width:520px;font-size:14px">
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold;width:170px">Reference</td>
                    <td style="padding:6px 10px">{self.x_referral_ref or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referred Contact</td>
                    <td style="padding:6px 10px">{self.partner_name or '—'}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referred Company</td>
                    <td style="padding:6px 10px">{self.x_referral_company or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referrer</td>
                    <td style="padding:6px 10px">{referrer_label}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referrer Phone</td>
                    <td style="padding:6px 10px">{referrer.phone if referrer else '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referrer Email</td>
                    <td style="padding:6px 10px">{referrer.email if referrer else '—'}</td>
                </tr>
            </table>
        """
        self._send_notification_email(
            subject=f'Referral Assigned to You: {self.x_referral_ref or self.name}',
            body_html=body,
            partner_ids=[self.user_id.partner_id.id],
        )

    def _notify_managers_converted(self):
        """Email managers when a referral is moved to the Converted stage."""
        self.ensure_one()
        manager_partners = self._get_referral_manager_partners()
        if not manager_partners:
            return
        referrer = self.x_referrer_id
        referrer_label = referrer.name if referrer else '—'
        if referrer and referrer.company:
            referrer_label += f' ({referrer.company})'
        body = f"""
            <p>A referral has been successfully converted to a client.</p>
            <table style="border-collapse:collapse;width:100%;max-width:520px;font-size:14px">
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold;width:170px">Reference</td>
                    <td style="padding:6px 10px">{self.x_referral_ref or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referred Company</td>
                    <td style="padding:6px 10px">{self.x_referral_company or '—'}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referrer</td>
                    <td style="padding:6px 10px">{referrer_label}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Deal Value</td>
                    <td style="padding:6px 10px">AED {self.x_deal_value:,.2f}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Commission</td>
                    <td style="padding:6px 10px">
                        AED {self.x_commission_amount:,.2f} ({self.x_commission_rate:.1f}%)
                    </td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Salesperson</td>
                    <td style="padding:6px 10px">{self.user_id.name if self.user_id else '—'}</td>
                </tr>
            </table>
            <p style="margin-top:12px">A commission record has been automatically created.</p>
        """
        self._send_notification_email(
            subject=f'Referral Converted: {self.x_referral_ref or self.name}',
            body_html=body,
            partner_ids=manager_partners.ids,
        )

    # ── ORM overrides ─────────────────────────────────────────────────────

    def write(self, vals):
        # Capture old salesperson before write to detect real changes
        old_user_ids = {}
        if 'user_id' in vals:
            old_user_ids = {
                rec.id: rec.user_id.id
                for rec in self
                if rec.x_is_referral
            }

        result = super().write(vals)

        # Notify new salesperson when assignment changes
        if 'user_id' in vals:
            for rec in self:
                if (rec.x_is_referral and rec.user_id
                        and rec.user_id.id != old_user_ids.get(rec.id)):
                    rec.sudo()._notify_salesperson_assigned()

        # Auto-create commission and notify managers on first conversion
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
        for vals in vals_list:
            if vals.get('x_is_referral') and not vals.get('user_id') and default_manager:
                vals['user_id'] = default_manager.id
        records = super().create(vals_list)
        for rec in records:
            if rec.x_is_referral:
                if not rec.x_referral_ref:
                    rec.x_referral_ref = f'REF-{rec.id:05d}'
                if not rec.partner_id:
                    partner = rec._find_or_create_referral_partner()
                    if partner:
                        rec.partner_id = partner.id
        # Notify managers of every new referral (portal or backend)
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
        return super()._read_group_stage_ids(stages, domain)

    @api.model
    def _get_default_referral_manager(self):
        """Return the first active, non-system user in group_referral_manager."""
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
        company_name = self.x_referral_company
        if not company_name and self.name:
            m = re.search(r'\(([^)]+)\)\s*$', self.name)
            if m:
                company_name = m.group(1)
        if not company_name:
            return self.env['res.partner'].browse()
        partner = self.env['res.partner'].search(
            [('name', '=ilike', company_name), ('is_company', '=', True)],
            limit=1,
        )
        if not partner:
            partner = self.env['res.partner'].create({
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
