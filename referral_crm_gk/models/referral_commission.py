import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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

    # Invoice (sourced from the linked lead)
    invoice_id = fields.Many2one(
        'account.move',
        related='lead_id.x_invoice_id',
        string='Invoice',
        store=True,
        readonly=True,
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

    # Invoice display fields
    invoice_number = fields.Char(
        related='invoice_id.name', string='Invoice Number', readonly=True,
    )
    invoice_date = fields.Date(
        related='invoice_id.invoice_date', string='Invoice Date', readonly=True,
    )
    invoice_amount_total = fields.Monetary(
        related='invoice_id.amount_total', string='Invoice Total (AED)',
        readonly=True, currency_field='currency_id',
    )
    invoice_amount_residual = fields.Monetary(
        related='invoice_id.amount_residual', string='Outstanding (AED)',
        readonly=True, currency_field='currency_id',
    )
    invoice_payment_state = fields.Selection(
        related='invoice_id.payment_state', string='Invoice Payment Status', readonly=True,
    )

    # Payment status — computed from invoice when linked; manual otherwise
    state = fields.Selection([
        ('pending', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
    ], string='Status',
       compute='_compute_state_from_invoice',
       inverse='_set_state',
       store=True,
       default='pending',
       tracking=True,
    )

    # Amount paid to referrer — manual field; view enforces readonly when invoice is linked
    amount_paid = fields.Float(
        string='Amount Paid (AED)', digits=(16, 2), default=0.0, tracking=True,
    )
    remaining_balance = fields.Float(
        compute='_compute_remaining_balance', store=True,
        string='Remaining Balance (AED)', digits=(16, 2),
    )
    paid_date = fields.Date(string='Paid On', tracking=True)
    payment_ref = fields.Char(string='Payment Reference', tracking=True)
    notes = fields.Text(string='Notes')

    _INVOICE_STATE_MAP = {
        'not_paid': 'pending',
        'partial': 'partial',
        'in_payment': 'partial',
        'paid': 'paid',
        'reversed': 'pending',
        'invoicing_legacy': 'pending',
    }

    @api.depends('invoice_id', 'invoice_id.payment_state',
                 'lead_id.x_payment_status', 'commission_amount', 'amount_paid')
    def _compute_state_from_invoice(self):
        for rec in self:
            if rec.invoice_id:
                # Invoice linked → always driven by accounting
                rec.state = self._INVOICE_STATE_MAP.get(
                    rec.invoice_id.payment_state, 'pending'
                )
            elif (rec.amount_paid or 0.0) >= (rec.commission_amount or 0.0) > 0:
                # Manual commission fully paid
                rec.state = 'paid'
            elif (rec.amount_paid or 0.0) > 0:
                # Manual commission partially paid
                rec.state = 'partial'
            else:
                rec.state = 'pending'

    def _set_state(self):
        # Allows manual writes for commissions without a linked invoice.
        pass

    @api.depends('commission_amount', 'amount_paid')
    def _compute_remaining_balance(self):
        for rec in self:
            rec.remaining_balance = max(0.0, (rec.commission_amount or 0.0) - (rec.amount_paid or 0.0))

    @api.depends('lead_id.x_referral_ref', 'lead_id.x_referral_company')
    def _compute_name(self):
        for rec in self:
            if rec.lead_id:
                ref = rec.lead_id.x_referral_ref or str(rec.lead_id.id)
                company = rec.lead_id.x_referral_company or ''
                rec.name = f'COM/{ref}' + (f' – {company}' if company else '')
            else:
                rec.name = 'New Commission'

    def _send_template_email(self, template_xml_id, extra_recipients=None):
        template = self.env.ref(
            f'referral_crm_gk.{template_xml_id}', raise_if_not_found=False
        )
        if not template:
            _logger.warning('referral_crm_gk: template %s not found', template_xml_id)
            return
        partners = extra_recipients.filtered('email') if extra_recipients else self.env['res.partner'].browse()
        if not partners:
            _logger.warning(
                'referral_crm_gk: no email recipients for template %s', template_xml_id
            )
            return
        template.send_mail(
            self.id,
            force_send=True,
            raise_exception=False,
            email_values={
                'recipient_ids': [(4, p.id) for p in partners],
                'email_to': '',
                'auto_delete': False,
            },
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

    def _notify_commission_paid(self):
        self.ensure_one()
        recipients = self._get_referral_manager_partners()
        if self.lead_id.user_id and self.lead_id.user_id.partner_id.email:
            recipients |= self.lead_id.user_id.partner_id
        if not recipients:
            return
        self._send_template_email('email_template_commission_paid', extra_recipients=recipients)

    def action_mark_paid(self):
        self.ensure_one()
        if self.invoice_id:
            raise UserError(
                "This commission is linked to invoice %s.\n\n"
                "Payment status is automatically synchronised from the Accounting module. "
                "Please record payments against the invoice to update the commission status."
                % (self.invoice_number or self.invoice_id.id)
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Record Payment',
            'res_model': 'referral.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_commission_id': self.id,
            },
        }

    def action_open_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_referral(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'res_id': self.lead_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
