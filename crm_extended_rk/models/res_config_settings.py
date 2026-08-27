# -*- coding: utf-8 -*-
from odoo import api, fields, models

JOURNEY_START_PARAM = 'crm_extended_rk.journey_reminders_start_date'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    journey_reminders_active = fields.Boolean(
        string='Lead Journey Reminders',
        config_parameter='crm_extended_rk.journey_reminders_active',
        help="Automatically schedule follow-up activities as a lead moves "
             "through the pipeline. Reminders go to the lead's salesperson.")

    # Deliberately NOT declared with config_parameter: res.config.settings
    # only accepts boolean/integer/float/char/selection/many2one/datetime for
    # those, and a Date field raises on default_get - which breaks the whole
    # Settings app, not just this section. Read and written by hand below.
    journey_reminders_start_date = fields.Date(
        string='Reminders Active From',
        help="Leads created before this date never receive automatic "
             "reminders. It is stamped with today's date when reminders are "
             "first switched on, so the existing pipeline backlog is left "
             "alone. Clearing it while reminders are on resets it to today "
             "rather than exposing every old lead.")

    journey_delay_send_discovery = fields.Integer(
        string='Send Discovery Form After (Days)', default=1,
        config_parameter='crm_extended_rk.delay_send_discovery')
    journey_delay_chase_discovery = fields.Integer(
        string='Chase Unanswered Form After (Days)', default=3,
        config_parameter='crm_extended_rk.delay_chase_discovery')
    journey_delay_prepare_proposal = fields.Integer(
        string='Prepare Proposal Within (Days)', default=2,
        config_parameter='crm_extended_rk.delay_prepare_proposal')
    journey_delay_chase_feedback = fields.Integer(
        string='Chase Client Feedback After (Days)', default=3,
        config_parameter='crm_extended_rk.delay_chase_feedback')
    journey_nudge_hours = fields.Integer(
        string='Alert If No Activity For (Hours)', default=48,
        config_parameter='crm_extended_rk.nudge_hours',
        help="Applies in every stage. Any open lead with nothing recorded "
             "against it for this many hours, and no reminder already "
             "waiting, alerts its salesperson and the Sales Managers.")

    def get_values(self):
        res = super().get_values()
        raw = self.env['ir.config_parameter'].sudo().get_param(JOURNEY_START_PARAM)
        res['journey_reminders_start_date'] = fields.Date.to_date(raw) if raw else False
        return res

    def set_values(self):
        res = super().set_values()
        for record in self:
            start = record.journey_reminders_start_date
            # A blank cut-off with reminders switched on would make all 148
            # backlog leads eligible at once - the exact blast this setting
            # exists to prevent. Fall back to today instead.
            if record.journey_reminders_active and not start:
                start = fields.Date.context_today(record)
            self.env['ir.config_parameter'].sudo().set_param(
                JOURNEY_START_PARAM,
                fields.Date.to_string(start) if start else False)
        return res

    @api.onchange('journey_reminders_active')
    def _onchange_journey_reminders_active(self):
        # Switching reminders on stamps today's date, so the pipeline backlog
        # that predates the feature is excluded by default. The user can still
        # move the date back deliberately.
        for record in self:
            if record.journey_reminders_active and not record.journey_reminders_start_date:
                record.journey_reminders_start_date = fields.Date.context_today(record)
