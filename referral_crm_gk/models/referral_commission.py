from odoo import api, fields, models


class ReferralCommission(models.Model):
    _name = 'referral.commission'
    _description = 'Referral Commission'
    _rec_name = 'name'
    _order = 'create_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', compute='_compute_name', store=True)

    lead_id = fields.Many2one(
        'crm.lead', string='Referral Lead',
        required=True, ondelete='cascade', readonly=True,
    )

    # Referrer (from lead)
    referrer_id = fields.Many2one(
        'referral.referrer', related='lead_id.x_referrer_id',
        string='Referrer', store=True,
    )
    referrer_company = fields.Char(
        related='lead_id.x_referrer_id.company', string='Referrer Company', store=True,
    )
    referrer_tier = fields.Selection(
        related='lead_id.x_referrer_tier', string='Tier', store=True,
    )
    referrer_email = fields.Char(related='lead_id.x_referrer_id.email', string='Referrer Email')
    referrer_phone = fields.Char(related='lead_id.x_referrer_id.phone', string='Referrer Phone')
    referrer_commission_rate = fields.Float(
        related='lead_id.x_commission_rate', string='Commission Rate (%)', store=True, digits=(5, 2),
    )

    # Referral (from lead)
    referral_company = fields.Char(
        related='lead_id.x_referral_company', string='Referred Company', store=True,
    )
    partner_name = fields.Char(related='lead_id.partner_name', string='Contact', store=True)
    referral_ref = fields.Char(related='lead_id.x_referral_ref', string='Referral Ref', store=True)

    currency_id = fields.Many2one(
        'res.currency', related='lead_id.company_currency', string='Currency',
    )

    # Deal values (live from lead/sale order)
    deal_value = fields.Float(
        related='lead_id.x_deal_value', string='Deal Value (AED)', store=True, digits=(16, 2),
    )
    commission_amount = fields.Float(
        related='lead_id.x_commission_amount', string='Commission Amount (AED)', store=True, digits=(16, 2),
    )

    # Payment
    state = fields.Selection([
        ('pending', 'Pending'),
        ('paid', 'Paid'),
    ], string='Status', default='pending', tracking=True)
    paid_date = fields.Date(string='Paid On', tracking=True)
    payment_ref = fields.Char(string='Payment Reference', tracking=True)
    notes = fields.Text(string='Notes')

    @api.depends('lead_id.x_referral_ref', 'lead_id.x_referral_company')
    def _compute_name(self):
        for rec in self:
            if rec.lead_id:
                ref = rec.lead_id.x_referral_ref or str(rec.lead_id.id)
                company = rec.lead_id.x_referral_company or ''
                rec.name = f'COM/{ref}' + (f' – {company}' if company else '')
            else:
                rec.name = 'New Commission'

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

    def _notify_commission_paid(self):
        """Email managers and the salesperson when a commission is marked paid."""
        self.ensure_one()
        recipients = self._get_referral_manager_partners()
        if self.lead_id.user_id and self.lead_id.user_id.partner_id.email:
            recipients |= self.lead_id.user_id.partner_id
        if not recipients:
            return
        referrer_label = self.referrer_id.name if self.referrer_id else '—'
        if self.referrer_company:
            referrer_label += f' ({self.referrer_company})'
        salesperson = self.lead_id.user_id.name if self.lead_id.user_id else '—'
        body = f"""
            <p>A referral commission has been marked as paid.</p>
            <table style="border-collapse:collapse;width:100%;max-width:520px;font-size:14px">
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold;width:170px">Commission Ref</td>
                    <td style="padding:6px 10px">{self.name or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Referrer</td>
                    <td style="padding:6px 10px">{referrer_label}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Referred Company</td>
                    <td style="padding:6px 10px">{self.referral_company or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Deal Value</td>
                    <td style="padding:6px 10px">AED {self.deal_value:,.2f}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Commission Amount</td>
                    <td style="padding:6px 10px">
                        AED {self.commission_amount:,.2f} ({self.referrer_commission_rate:.1f}%)
                    </td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Paid On</td>
                    <td style="padding:6px 10px">{self.paid_date or '—'}</td>
                </tr>
                <tr style="background:#f5f5f5">
                    <td style="padding:6px 10px;font-weight:bold">Payment Reference</td>
                    <td style="padding:6px 10px">{self.payment_ref or '—'}</td>
                </tr>
                <tr>
                    <td style="padding:6px 10px;font-weight:bold">Salesperson</td>
                    <td style="padding:6px 10px">{salesperson}</td>
                </tr>
            </table>
        """
        self._send_notification_email(
            subject=f'Commission Paid: {self.name}',
            body_html=body,
            partner_ids=recipients.ids,
        )

    def action_mark_paid(self):
        self.ensure_one()
        self.write({
            'state': 'paid',
            'paid_date': fields.Date.today(),
        })
        if self.lead_id:
            self.lead_id.x_payment_status = 'full'
        self._notify_commission_paid()

    def action_view_referral(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
