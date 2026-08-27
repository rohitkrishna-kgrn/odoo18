# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

# The vocabulary of the lead journey. Order here is the order shown in the
# filter dropdowns, so it follows the real-life sequence of a deal.
EVENT_TYPE_SELECTION = [
    ('lead_created', 'Lead Created'),
    ('stage_change', 'Stage Changed'),
    ('discovery_sent', 'Discovery Form Sent'),
    ('discovery_received', 'Discovery Form Received'),
    ('proposal_created', 'Proposal Created'),
    ('proposal_sent', 'Proposal Shared'),
    ('proposal_approved', 'Proposal Approved'),
    ('proposal_confirmed', 'Order Confirmed'),
    ('proposal_cancelled', 'Proposal Cancelled'),
    ('client_followup', 'Client Follow-up'),
    ('client_update', 'Client Update'),
    ('client_feedback', 'Client Feedback Received'),
    ('activity_done', 'Activity Completed'),
    ('other', 'Other Activity'),
]


class CrmLeadEvent(models.Model):
    """One row per meaningful thing that happened to a lead.

    Append-only audit trail. Nobody types into it by hand: every row is
    written by a hook on the action that caused it (stage move, discovery
    form send/receive, quotation milestone, completed activity). It exists
    because the timing data it answers questions about is otherwise
    scattered across create_date, chatter tracking values, the discovery
    form record and the sale order - with no way to line them up.
    """
    _name = 'crm.lead.event'
    _description = 'CRM Lead Journey Event'
    # Chronological: the Journey tab on the lead reads top-to-bottom as a
    # timeline. The standalone list view flips this with default_order.
    _order = 'event_date asc, id asc'

    lead_id = fields.Many2one(
        'crm.lead', string='Opportunity', required=True,
        ondelete='cascade', index=True)
    event_date = fields.Datetime(
        string='Date', required=True, default=fields.Datetime.now, index=True)
    event_type = fields.Selection(
        EVENT_TYPE_SELECTION, string='Action', required=True, index=True)
    name = fields.Char(string='Description', required=True)
    note = fields.Text(string='Details')

    # Stage context. stage_id is the stage the lead was in *after* the event;
    # stage_from_id is only filled for an actual stage move.
    stage_id = fields.Many2one('crm.stage', string='Stage', ondelete='set null')
    stage_from_id = fields.Many2one('crm.stage', string='Moved From', ondelete='set null')

    user_id = fields.Many2one('res.users', string='Done By', ondelete='set null')
    # Set when the row came from someone ticking off a reminder. Needed
    # because most reminder types map to a richer event_type
    # (client_followup, client_feedback, ...), so counting rows literally
    # typed 'activity_done' silently undercounts completed work.
    from_activity = fields.Boolean(
        string='From a Reminder', default=False, index=True)
    salesperson_id = fields.Many2one(
        related='lead_id.user_id', string='Salesperson', store=True, index=True)
    team_id = fields.Many2one(
        related='lead_id.team_id', string='Sales Team', store=True)
    partner_id = fields.Many2one(
        related='lead_id.partner_id', string='Customer', store=True)

    # Where the event came from, so the timeline can link straight to it.
    discovery_form_id = fields.Many2one(
        'crm.lead.discovery.form', string='Discovery Form', ondelete='set null')
    order_id = fields.Many2one('sale.order', string='Quotation', ondelete='set null')

    # Gaps are deliberately NOT stored: they depend on sibling rows, so a
    # stored version would need every event of a lead recomputed whenever any
    # one of them moved. Aggregate reporting uses crm.lead.journey.report
    # (a SQL view) instead, which does the arithmetic in the database.
    days_since_previous = fields.Float(
        string='Days Since Previous', compute='_compute_journey_gaps',
        digits=(16, 2), help="Time between this action and the one before it.")
    days_since_created = fields.Float(
        string='Days Since Lead Created', compute='_compute_journey_gaps',
        digits=(16, 2))

    @api.depends('event_date', 'lead_id', 'lead_id.journey_event_ids.event_date')
    def _compute_journey_gaps(self):
        # Sort each lead's events once, not once per row.
        ordered_by_lead = {}
        for event in self:
            lead = event.lead_id
            if lead.id not in ordered_by_lead:
                ordered_by_lead[lead.id] = lead.journey_event_ids.sorted(
                    key=lambda e: (e.event_date or fields.Datetime.now(), e.id))
        for event in self:
            siblings = ordered_by_lead.get(event.lead_id.id, self.browse())
            previous_date = False
            for sibling in siblings:
                if sibling == event:
                    break
                previous_date = sibling.event_date or previous_date
            created = event.lead_id.create_date
            event.days_since_previous = self._days_between(previous_date, event.event_date)
            event.days_since_created = self._days_between(created, event.event_date)

    @staticmethod
    def _days_between(start, end):
        if not start or not end:
            return 0.0
        return (end - start).total_seconds() / 86400.0

    def unlink(self):
        # The log is evidence of what happened; letting a salesperson delete
        # rows would make every duration report untrustworthy. Managers can
        # still clean up through the Settings/technical menu.
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise UserError(_(
                "Journey events are an audit trail and cannot be deleted."))
        return super().unlink()
