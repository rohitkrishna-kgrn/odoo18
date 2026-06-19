from odoo import fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    x_is_referral_stage = fields.Boolean(
        string='Is Referral Stage',
        default=False,
        help='When enabled this stage appears only in the Referral pipeline.',
    )
    x_is_referral_converted = fields.Boolean(
        string='Is Referral Converted Stage',
        default=False,
        help='Mark as the Converted stage for referral commission calculation.',
    )
    x_is_referral_lost = fields.Boolean(
        string='Is Referral Lost Stage',
        default=False,
        help='Mark as the Not Qualified / Lost stage for referrals.',
    )
    x_color_hex = fields.Char(
        string='Colour Code',
        help='Hex colour code for this stage (e.g. #3949AB).',
    )
    x_entry_criteria = fields.Char(
        string='Entry Criteria',
        help='Condition that must be met before a lead moves into this stage.',
    )
    x_stage_description = fields.Text(
        string='Stage Description',
        help='Expected actions and notes for this pipeline stage.',
    )
