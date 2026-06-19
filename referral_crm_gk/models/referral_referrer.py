from odoo import api, fields, models


class ReferralReferrer(models.Model):
    _name = 'referral.referrer'
    _description = 'KGRN Referral Partner'
    _rec_name = 'name'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Full Name', required=True)
    company = fields.Char(string='Company / Organisation')
    email = fields.Char(string='Email Address')
    phone = fields.Char(string='Phone Number')

    lead_ids = fields.One2many('crm.lead', 'x_referrer_id', string='Referrals')

    total_referrals = fields.Integer(
        compute='_compute_stats',
        store=True,
        string='Total Referrals',
    )
    total_conversions = fields.Integer(
        compute='_compute_stats',
        store=True,
        string='Total Conversions',
    )
    tier = fields.Selection([
        ('starter', 'Starter'),
        ('active', 'Active'),
        ('premier', 'Premier'),
    ], compute='_compute_tier', store=True, string='Tier')

    commission_rate = fields.Float(
        compute='_compute_tier',
        store=True,
        string='Commission Rate (%)',
        digits=(5, 2),
    )
    total_commission_earned = fields.Float(
        compute='_compute_total_commission',
        store=True,
        string='Total Commission Earned (AED)',
        digits=(16, 2),
    )
    currency_id = fields.Many2one(
        'res.currency',
        compute='_compute_currency_id',
        string='Currency',
    )

    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = self.env.company.currency_id

    @api.depends('lead_ids.stage_id', 'lead_ids.stage_id.x_is_referral_converted')
    def _compute_stats(self):
        for rec in self:
            leads = rec.lead_ids
            rec.total_referrals = len(leads)
            rec.total_conversions = len(
                leads.filtered(lambda l: l.stage_id.x_is_referral_converted)
            )

    @api.depends('total_conversions')
    def _compute_tier(self):
        for rec in self:
            c = rec.total_conversions
            if c >= 5:
                rec.tier = 'premier'
                rec.commission_rate = 15.0
            elif c >= 3:
                rec.tier = 'active'
                rec.commission_rate = 12.0
            else:
                rec.tier = 'starter'
                rec.commission_rate = 10.0

    @api.depends('lead_ids.x_commission_amount', 'lead_ids.stage_id.x_is_referral_converted')
    def _compute_total_commission(self):
        for rec in self:
            converted = rec.lead_ids.filtered(lambda l: l.stage_id.x_is_referral_converted)
            rec.total_commission_earned = sum(converted.mapped('x_commission_amount'))

    def action_view_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Referrals – {self.name}',
            'res_model': 'crm.lead',
            'view_mode': 'list,kanban,form',
            'domain': [('x_referrer_id', '=', self.id)],
            'context': {'default_x_referrer_id': self.id, 'default_x_is_referral': True},
        }
