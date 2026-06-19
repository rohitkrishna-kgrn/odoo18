from datetime import datetime

from odoo import api, fields, models


class ReferralDashboard(models.TransientModel):
    _name = 'referral.dashboard'
    _description = 'Referral CRM Dashboard'

    name = fields.Char(default='KGRN Referral Dashboard', readonly=True)
    greeting_text = fields.Char(string='Greeting', readonly=True)
    is_manager = fields.Boolean(readonly=True)
    total_referrals = fields.Integer(string='Total Referrals', readonly=True)
    in_pipeline = fields.Integer(string='In Pipeline', readonly=True)
    total_converted = fields.Integer(string='Converted', readonly=True)
    pipeline_value = fields.Float(
        string='Pipeline Value (AED)', readonly=True, digits=(16, 2)
    )
    commission_liability = fields.Float(
        string='Commission (AED)', readonly=True, digits=(16, 2)
    )
    active_referrers = fields.Integer(string='Active Referrers', readonly=True)

    @api.model
    def action_open_dashboard(self):
        Lead = self.env['crm.lead']
        is_manager = self.env.user.has_group('referral_crm_gk.group_referral_manager')

        if is_manager:
            all_referrals = Lead.search([('x_is_referral', '=', True)])
        else:
            all_referrals = Lead.search([
                ('x_is_referral', '=', True),
                ('user_id', '=', self.env.uid),
            ])

        converted = all_referrals.filtered(
            lambda l: l.stage_id.x_is_referral_converted
        )
        active = all_referrals.filtered(
            lambda l: not l.stage_id.x_is_referral_converted
            and not l.stage_id.x_is_referral_lost
        )
        commission_paid = converted.filtered(lambda l: l.x_payment_status == 'full')

        active_referrers = 0
        if is_manager:
            active_referrers = len(self.env['referral.referrer'].search([
                ('lead_ids', 'in', all_referrals.ids),
            ]))

        hour = datetime.now().hour
        time_of_day = 'morning' if hour < 12 else ('afternoon' if hour < 17 else 'evening')
        first_name = (self.env.user.name or '').split()[0]
        greeting = f'Good {time_of_day}, {first_name}!'

        rec = self.create({
            'greeting_text': greeting,
            'is_manager': is_manager,
            'total_referrals': len(all_referrals),
            'in_pipeline': len(active),
            'total_converted': len(converted),
            'pipeline_value': sum(active.mapped('expected_revenue')),
            'commission_liability': sum(commission_paid.mapped('x_commission_amount')),
            'active_referrers': active_referrers,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Referral Dashboard',
            'res_model': 'referral.dashboard',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_pipeline(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Referral Pipeline',
            'res_model': 'crm.lead',
            'view_mode': 'kanban,list,form',
            'domain': [('x_is_referral', '=', True)],
            'context': {'default_x_is_referral': True},
        }

    def action_view_referrers(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Referrers',
            'res_model': 'referral.referrer',
            'view_mode': 'list,form',
        }

    def action_view_my_leads(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'My Leads',
            'res_model': 'crm.lead',
            'view_mode': 'list,kanban,form',
            'domain': [
                ('x_is_referral', '=', True),
                ('user_id', '=', self.env.uid),
            ],
            'context': {'default_x_is_referral': True},
        }
