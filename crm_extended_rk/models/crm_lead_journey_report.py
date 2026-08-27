# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools


class CrmLeadJourneyReport(models.Model):
    """One row per stage the lead has occupied, with how long it sat there.

    Built as a SQL view rather than stored fields because "days in stage" is
    a moving target for any open lead - storing it would mean recomputing
    every lead every night. The window function derives each occupancy from
    the journey log: a row starts when the lead enters a stage and ends when
    the next event moves it on (or right now, if it is still sitting there).
    """
    _name = 'crm.lead.journey.report'
    _description = 'Lead Journey Analysis'
    _auto = False
    _order = 'entered_on desc'

    lead_id = fields.Many2one('crm.lead', string='Opportunity', readonly=True)
    lead_name = fields.Char(string='Opportunity Name', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Customer', readonly=True)
    user_id = fields.Many2one('res.users', string='Salesperson', readonly=True)
    team_id = fields.Many2one('crm.team', string='Sales Team', readonly=True)
    stage_id = fields.Many2one('crm.stage', string='Stage', readonly=True)

    lead_created_on = fields.Datetime(string='Lead Created', readonly=True)
    entered_on = fields.Datetime(string='Entered Stage', readonly=True)
    left_on = fields.Datetime(string='Left Stage', readonly=True)
    days_in_stage = fields.Float(string='Days in Stage', readonly=True, aggregator='avg')
    days_to_reach_stage = fields.Float(
        string='Days to Reach Stage', readonly=True, aggregator='avg',
        help="Time from lead creation until it entered this stage.")
    is_current_stage = fields.Boolean(string='Current Stage', readonly=True)
    is_open = fields.Boolean(string='Lead Open', readonly=True)

    days_to_conversion = fields.Float(
        string='Days to Conversion', readonly=True, aggregator='avg',
        help="Total time from lead creation to reaching Won. "
             "Empty while the lead is still open.")
    activity_done_count = fields.Integer(
        string='Activities Completed', readonly=True, aggregator='avg')
    activity_pending_count = fields.Integer(
        string='Activities Pending', readonly=True, aggregator='avg')

    @api.model
    def _query(self):
        return """
            WITH stage_events AS (
                SELECT e.id,
                       e.lead_id,
                       e.stage_id,
                       e.event_date,
                       LEAD(e.event_date) OVER (
                           PARTITION BY e.lead_id
                           ORDER BY e.event_date, e.id) AS next_event_date
                  FROM crm_lead_event e
                 WHERE e.event_type IN ('lead_created', 'stage_change')
                   AND e.stage_id IS NOT NULL
            ),
            conversion AS (
                SELECT e.lead_id, MIN(e.event_date) AS won_on
                  FROM crm_lead_event e
                  JOIN crm_stage s ON s.id = e.stage_id
                 WHERE s.is_won = TRUE
              GROUP BY e.lead_id
            ),
            activity_done AS (
                SELECT e.lead_id, COUNT(*) AS done_count
                  FROM crm_lead_event e
                 WHERE e.from_activity
              GROUP BY e.lead_id
            ),
            activity_open AS (
                SELECT a.res_id AS lead_id, COUNT(*) AS pending_count
                  FROM mail_activity a
                 WHERE a.res_model = 'crm.lead'
              GROUP BY a.res_id
            )
            SELECT se.id                              AS id,
                   se.lead_id                         AS lead_id,
                   l.name                             AS lead_name,
                   l.partner_id                       AS partner_id,
                   l.user_id                          AS user_id,
                   l.team_id                          AS team_id,
                   se.stage_id                        AS stage_id,
                   l.create_date                      AS lead_created_on,
                   se.event_date                      AS entered_on,
                   se.next_event_date                 AS left_on,
                   -- The clock on an unfinished occupancy only runs to "now"
                   -- when the lead really is still sitting in that stage and
                   -- still open. Three cases stop it early:
                   --   * the log's last stage disagrees with the lead's actual
                   --     stage - history is incomplete, so don't invent time;
                   --   * the stage is terminal (won / lost / not qualified) -
                   --     the deal ended there, it isn't "waiting";
                   --   * the lead is archived.
                   -- Without this, "days in Won" grows forever and poisons
                   -- every average on the report.
                   EXTRACT(EPOCH FROM (
                       COALESCE(
                           se.next_event_date,
                           CASE
                               WHEN se.stage_id <> l.stage_id THEN se.event_date
                               WHEN st.is_won AND l.date_closed IS NOT NULL
                                    THEN GREATEST(l.date_closed, se.event_date)
                               WHEN st.is_won OR term.res_id IS NOT NULL
                                    THEN se.event_date
                               WHEN NOT l.active THEN se.event_date
                               ELSE NOW() AT TIME ZONE 'UTC'
                           END)
                       - se.event_date)) / 86400.0    AS days_in_stage,
                   EXTRACT(EPOCH FROM (
                       se.event_date - l.create_date)) / 86400.0
                                                      AS days_to_reach_stage,
                   (se.next_event_date IS NULL
                    AND l.active
                    AND se.stage_id = l.stage_id)     AS is_current_stage,
                   l.active                           AS is_open,
                   CASE WHEN c.won_on IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (c.won_on - l.create_date)) / 86400.0
                   END                                AS days_to_conversion,
                   COALESCE(ad.done_count, 0)         AS activity_done_count,
                   COALESCE(ao.pending_count, 0)      AS activity_pending_count
              FROM stage_events se
              JOIN crm_lead l        ON l.id = se.lead_id
              JOIN crm_stage st      ON st.id = se.stage_id
              -- The two custom terminal stages have no is_won flag, so they
              -- are identified by their external id rather than by name,
              -- which a user could rename at any time.
              LEFT JOIN ir_model_data term
                     ON term.model = 'crm.stage'
                    AND term.res_id = se.stage_id
                    AND term.module = 'crm_extended_rk'
                    AND term.name IN ('stage_lost', 'stage_not_qualified')
              LEFT JOIN conversion c ON c.lead_id = se.lead_id
              LEFT JOIN activity_done ad ON ad.lead_id = se.lead_id
              LEFT JOIN activity_open ao ON ao.lead_id = se.lead_id
        """

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            "CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query()))
