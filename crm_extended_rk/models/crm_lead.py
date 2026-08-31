# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .crm_tag import APPROVED_TAG_DOMAIN
from .discovery_schema import form_selection


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Restricting the field itself rather than each view: a domain set here
    # applies to the form, the list, the kanban, the quick-create card, the
    # search panel and anything added later, so no occurrence can be missed.
    tag_ids = fields.Many2many(domain=APPROVED_TAG_DOMAIN)

    discovery_form_type = fields.Selection(
        selection='_selection_discovery_form_type',
        string='Discovery Form', tracking=True,
        help="Select which service this opportunity concerns, then use "
             "'Send Discovery Form' to email the matching client form. "
             "You can send more than one form (of the same or different type) "
             "over the life of this opportunity.")

    def _selection_discovery_form_type(self):
        return form_selection()

    discovery_form_ids = fields.One2many(
        'crm.lead.discovery.form', 'lead_id', string='Discovery Forms', copy=False)
    discovery_form_count = fields.Integer(
        string='Discovery Forms Sent', compute='_compute_discovery_form_count')

    @api.depends('discovery_form_ids')
    def _compute_discovery_form_count(self):
        for lead in self:
            lead.discovery_form_count = len(lead.discovery_form_ids)

    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order', copy=False, readonly=True,
        help="Quotation / sale order created from this pipeline.")

    stage_reason_ids = fields.One2many(
        'crm.lead.stage.reason', 'lead_id', string='Qualification Reasons', copy=False)

    # Stage flags used to show/hide the manual stage buttons in the header.
    is_stage_new = fields.Boolean(compute='_compute_stage_flags')
    is_stage_lost = fields.Boolean(compute='_compute_stage_flags')
    is_stage_qualified = fields.Boolean(compute='_compute_stage_flags')
    is_stage_not_qualified = fields.Boolean(compute='_compute_stage_flags')

    @api.depends('stage_id')
    def _compute_stage_flags(self):
        new_stage = self.env.ref('crm.stage_lead1', raise_if_not_found=False)
        qualified_stage = self.env.ref('crm.stage_lead2', raise_if_not_found=False)
        not_qualified_stage = self.env.ref('crm_extended_rk.stage_not_qualified', raise_if_not_found=False)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        for lead in self:
            lead.is_stage_new = bool(new_stage and lead.stage_id == new_stage)
            lead.is_stage_qualified = bool(qualified_stage and lead.stage_id == qualified_stage)
            lead.is_stage_not_qualified = bool(not_qualified_stage and lead.stage_id == not_qualified_stage)
            lead.is_stage_lost = bool(lost_stage and lead.stage_id == lost_stage)

    # ==================================================================
    # Pipeline stage automation
    #   Draft quotation created ----> Proposition   (see sale_order.py)
    #   Approved / Confirmed / Cancelled ------------> SE / Won / Lost
    #   Lost button ----------------> Lost stage
    #   Manual buttons: New -> Qualified, Lost -> New
    # ==================================================================
    def _move_stage(self, stage_xmlid):
        stage = self.env.ref(stage_xmlid, raise_if_not_found=False)
        if stage:
            self.write({'stage_id': stage.id, 'active': True})

    def action_move_to_qualified(self):
        """Header button shown while in the New stage."""
        self.ensure_one()
        self._move_stage('crm.stage_lead2')

    def action_move_to_new(self):
        """Header button shown while in the Lost stage."""
        self._move_stage('crm.stage_lead1')

    def _action_open_reason_wizard(self, title, target_stage_xmlid):
        """Popup asking why the lead is moving to target_stage_xmlid; the
        wizard logs the reason on the chatter and applies the move."""
        self.ensure_one()
        target_stage = self.env.ref(target_stage_xmlid, raise_if_not_found=False)
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.set.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lead_id': self.id,
                'default_target_stage_id': target_stage.id if target_stage else False,
            },
        }

    def action_open_not_qualified_wizard(self):
        """Header button shown in the New / Qualified stages."""
        return self._action_open_reason_wizard(
            _("Mark as Not Qualified"), 'crm_extended_rk.stage_not_qualified')

    def action_open_qualified_wizard(self):
        """Header button shown in the Not Qualified stage."""
        return self._action_open_reason_wizard(
            _("Mark as Qualified"), 'crm.stage_lead2')

    def action_set_lost(self, **additional_values):
        # The standard "Lost" button archives the lead; in addition we drop it
        # into the dedicated "Lost" pipeline column and keep it visible there.
        res = super().action_set_lost(**additional_values)
        lost_stage = self.env.ref('crm_extended_rk.stage_lost', raise_if_not_found=False)
        if lost_stage:
            self.write({'stage_id': lost_stage.id, 'active': True})
        return res

    # ------------------------------------------------------------------
    # Discovery form: prefill helper (used by the public controller)
    # ------------------------------------------------------------------
    def _discovery_prefill(self):
        """Values pushed into the public form so the client doesn't retype them."""
        self.ensure_one()
        company = self.partner_name or (self.partner_id.name if self.partner_id else '')
        return {
            'company_name': company or '',
            'contact_name': self.contact_name or (self.partner_id.name if self.partner_id else ''),
            'email': self.email_from or '',
            'phone': self.phone or self.mobile or '',
        }

    # ------------------------------------------------------------------
    # Discovery form: send a new one / browse the ones already sent
    # ------------------------------------------------------------------
    def action_send_discovery_form(self):
        """Header button: create and send a new discovery form submission of
        whichever type is currently selected. Can be clicked repeatedly to
        send further forms (same or different type) over the opportunity's
        lifetime."""
        self.ensure_one()
        if not self.discovery_form_type:
            raise UserError(_("Please select which Discovery Form to send first."))
        if not self.email_from:
            raise UserError(_(
                "Please set the email address on this pipeline before sending the "
                "discovery form."))

        submission = self.env['crm.lead.discovery.form'].create({
            'lead_id': self.id,
            'form_type': self.discovery_form_type,
        })
        submission.action_send()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Discovery Form Sent"),
                'message': _("The %(form)s discovery form link has been sent to %(email)s.") % {
                    'form': submission.form_label, 'email': self.email_from},
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'crm.lead',
                    'res_id': self.id,
                    'views': [[False, 'form']],
                    'target': 'current',
                },
            },
        }

    def action_view_discovery_forms(self):
        """Smart button: browse every discovery form sent for this opportunity."""
        self.ensure_one()
        return {
            'name': _("Discovery Forms"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.discovery.form',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id, 'default_form_type': self.discovery_form_type},
        }

    # ==================================================================
    # Journey tracking
    #   Every meaningful action on a lead is appended to crm.lead.event so
    #   the timeline, the durations and the management reports all read
    #   from one place. Rows are written by hooks, never typed by hand.
    # ==================================================================
    journey_event_ids = fields.One2many(
        'crm.lead.event', 'lead_id', string='Journey', copy=False)
    journey_event_count = fields.Integer(
        string='Journey Events', compute='_compute_journey_stats')
    days_in_current_stage = fields.Float(
        string='Days in Current Stage', compute='_compute_journey_stats', digits=(16, 2))
    lead_age_days = fields.Float(
        string='Lead Age (Days)', compute='_compute_journey_stats', digits=(16, 2))
    days_to_conversion = fields.Float(
        string='Days to Conversion', compute='_compute_journey_stats', digits=(16, 2),
        help="Time from lead creation to the moment it reached Won. "
             "Zero while the lead is still open.")
    activity_done_count = fields.Integer(
        string='Activities Completed', compute='_compute_journey_stats')
    activity_pending_count = fields.Integer(
        string='Activities Pending', compute='_compute_journey_stats')

    @api.depends('journey_event_ids', 'journey_event_ids.from_activity',
                 'journey_event_ids.stage_id', 'journey_event_ids.event_date',
                 'stage_id', 'date_last_stage_update', 'create_date',
                 'date_closed', 'activity_ids')
    def _compute_journey_stats(self):
        now = fields.Datetime.now()
        won_stage = self.env.ref('crm.stage_lead4', raise_if_not_found=False)
        for lead in self:
            events = lead.journey_event_ids
            lead.journey_event_count = len(events)
            lead.activity_pending_count = len(lead.activity_ids)
            lead.activity_done_count = len(events.filtered('from_activity'))

            created = lead.create_date
            lead.lead_age_days = self.env['crm.lead.event']._days_between(created, now)

            # NOT date_last_stage_update: core maintains it inconsistently
            # (its compute assigns only when the field is empty, so whether it
            # tracks the latest move depends on the write path), and a stale
            # one reports the lead's whole age as time in the current stage.
            # The journey log records every move, so derive it from there.
            stage_moves = events.filtered(
                lambda e: e.event_type in ('lead_created', 'stage_change')
                and e.stage_id).sorted('event_date')
            if stage_moves and stage_moves[-1].stage_id == lead.stage_id:
                stage_since = stage_moves[-1].event_date
            else:
                # The log disagrees with the lead's actual stage - something
                # moved it without leaving a trace. Fall back rather than
                # quoting a duration we cannot stand behind.
                stage_since = lead.date_last_stage_update or created
            lead.days_in_current_stage = self.env['crm.lead.event']._days_between(
                stage_since, now)

            # Conversion = the first time this lead landed in Won. Falls back to
            # date_closed for leads converted before the journey log existed.
            conversion_date = False
            if won_stage:
                reached_won = events.filtered(
                    lambda e: e.stage_id == won_stage).sorted('event_date')
                if reached_won:
                    conversion_date = reached_won[0].event_date
            if not conversion_date and won_stage and lead.stage_id == won_stage:
                conversion_date = lead.date_closed
            lead.days_to_conversion = self.env['crm.lead.event']._days_between(
                created, conversion_date)

    def _log_journey_event(self, event_type, name, **vals):
        """Append one row to the journey log for every lead in self.

        sudo() throughout: events are written from places the acting user may
        not be able to create records in - the public discovery-form
        controller runs as the portal/public user, and a colleague's lead is
        off-limits under crm.crm_rule_personal_lead.
        """
        events = self.env['crm.lead.event'].sudo()
        if not self:
            return events
        note = vals.pop('note', None) or self.env.context.get('journey_note')
        for lead in self:
            events |= events.create(dict(
                {
                    'lead_id': lead.id,
                    'event_type': event_type,
                    'name': name,
                    'note': note,
                    'stage_id': lead.stage_id.id,
                    'user_id': self.env.user.id,
                    'event_date': fields.Datetime.now(),
                },
                **vals))
        return events

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        for lead in leads:
            lead._log_journey_event(
                'lead_created',
                _("Lead created"),
                note=_("Source: %s") % (lead.source_id.name or _("not set")))
        leads._journey_on_lead_created()
        return leads

    def write(self, vals):
        # Capture the old stage before super(), which overwrites it.
        previous_stages = {}
        if 'stage_id' in vals:
            previous_stages = {lead.id: lead.stage_id for lead in self}
        res = super().write(vals)
        if previous_stages:
            for lead in self:
                old_stage = previous_stages.get(lead.id)
                if old_stage == lead.stage_id:
                    continue
                lead._log_journey_event(
                    'stage_change',
                    _("Stage: %(old)s → %(new)s") % {
                        'old': old_stage.name or _("none"),
                        'new': lead.stage_id.name or _("none"),
                    },
                    stage_from_id=old_stage.id if old_stage else False)
                # Won / Lost / Not Qualified: the conversation is over, so
                # stop chasing. Any other move leaves reminders in place.
                closing = [
                    self.env.ref(xmlid, raise_if_not_found=False)
                    for xmlid in self._JOURNEY_CLOSING_STAGES
                ]
                if lead.stage_id in self.env['crm.stage'].browse(
                        [stage.id for stage in closing if stage]):
                    lead._clear_journey_reminders()
        return res

    def action_view_journey(self):
        """Smart button: the full timeline for this opportunity."""
        self.ensure_one()
        return {
            'name': _("Lead Journey"),
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead.event',
            'view_mode': 'list,form',
            'domain': [('lead_id', '=', self.id)],
            'context': {'default_lead_id': self.id, 'create': False},
        }

    # ------------------------------------------------------------------
    # One-off history rebuild
    # ------------------------------------------------------------------
    @api.model
    def _backfill_journey_events(self):
        """Reconstruct the journey log for leads that predate this feature.

        Idempotent: a lead that already has events is skipped, so re-running
        it on every module upgrade is harmless. It only ever writes dates it
        can actually evidence - creation dates, recorded stage moves,
        discovery form timestamps and quotation dates. Nothing is invented:
        actions that left no trace in the database (a proposal emailed before
        this feature existed, a phone follow-up) simply are not in the log,
        and the reports will show that gap honestly.
        """
        Event = self.env['crm.lead.event'].sudo()

        # Normalise rows written before from_activity existed. Idempotent, and
        # outside the early return below so it still runs once every lead has
        # been backfilled.
        self.env.cr.execute("""
            UPDATE crm_lead_event
               SET from_activity = TRUE
             WHERE event_type = 'activity_done'
               AND from_activity IS NOT TRUE
        """)

        leads = self.with_context(active_test=False).search([])
        self.env.cr.execute("SELECT DISTINCT lead_id FROM crm_lead_event")
        already_logged = {row[0] for row in self.env.cr.fetchall()}
        todo = leads.filtered(lambda lead: lead.id not in already_logged)
        if not todo:
            return 0

        stage_names = {s.id: s.name for s in self.env['crm.stage'].search([])}
        partner_to_user = {
            u.partner_id.id: u.id
            for u in self.env['res.users'].with_context(active_test=False).search([])
        }

        # Recorded stage moves live in the chatter as tracking values. Read
        # them in one query rather than walking every lead's message history.
        self.env.cr.execute("""
            SELECT m.res_id, v.old_value_integer, v.new_value_integer,
                   m.date, m.author_id
              FROM mail_tracking_value v
              JOIN mail_message m ON m.id = v.mail_message_id
              JOIN ir_model_fields f ON f.id = v.field_id
             WHERE m.model = 'crm.lead'
               AND f.name = 'stage_id'
               AND f.model = 'crm.lead'
               AND m.res_id IN %s
          ORDER BY m.res_id, m.date
        """, (tuple(todo.ids),))
        moves_by_lead = {}
        for res_id, old_stage, new_stage, date, author in self.env.cr.fetchall():
            moves_by_lead.setdefault(res_id, []).append(
                (old_stage, new_stage, date, author))

        vals_list = []
        for lead in todo:
            moves = moves_by_lead.get(lead.id, [])
            # The stage the lead started in: whatever the first recorded move
            # moved away from, else the stage it is still sitting in.
            opening_stage = moves[0][0] if moves else lead.stage_id.id
            vals_list.append({
                'lead_id': lead.id,
                'event_date': lead.create_date,
                'event_type': 'lead_created',
                'name': _("Lead created"),
                'note': _("Reconstructed from history"),
                'stage_id': opening_stage or False,
                'user_id': lead.create_uid.id,
            })
            for old_stage, new_stage, date, author in moves:
                vals_list.append({
                    'lead_id': lead.id,
                    'event_date': date,
                    'event_type': 'stage_change',
                    'name': _("Stage: %(old)s → %(new)s") % {
                        'old': stage_names.get(old_stage) or _("none"),
                        'new': stage_names.get(new_stage) or _("none"),
                    },
                    'note': _("Reconstructed from history"),
                    'stage_from_id': old_stage or False,
                    'stage_id': new_stage or False,
                    'user_id': partner_to_user.get(author, False),
                })
            for form in lead.discovery_form_ids:
                if form.sent_date:
                    vals_list.append({
                        'lead_id': lead.id,
                        'event_date': form.sent_date,
                        'event_type': 'discovery_sent',
                        'name': _("%s discovery form sent") % form.form_label,
                        'note': _("Reconstructed from history"),
                        'discovery_form_id': form.id,
                        'user_id': form.create_uid.id,
                    })
                if form.submitted_date:
                    vals_list.append({
                        'lead_id': lead.id,
                        'event_date': form.submitted_date,
                        'event_type': 'discovery_received',
                        'name': _("%s discovery form received back from client")
                                % form.form_label,
                        'note': _("Reconstructed from history"),
                        'discovery_form_id': form.id,
                    })
            for order in lead.order_ids:
                vals_list.append({
                    'lead_id': lead.id,
                    'event_date': order.create_date,
                    'event_type': 'proposal_created',
                    'name': _("Proposal %s created") % order.name,
                    'note': _("Reconstructed from history"),
                    'order_id': order.id,
                    'user_id': order.create_uid.id,
                })
                if order.state in ('sale', 'done') and order.date_order:
                    vals_list.append({
                        'lead_id': lead.id,
                        'event_date': order.date_order,
                        'event_type': 'proposal_confirmed',
                        'name': _("Order %s confirmed") % order.name,
                        'note': _("Reconstructed from history"),
                        'order_id': order.id,
                    })

        # Drop rows the source data left dateless rather than defaulting them
        # to today, which would fabricate a duration.
        vals_list = [v for v in vals_list if v.get('event_date')]
        if vals_list:
            Event.create(vals_list)
        return len(vals_list)

    # ==================================================================
    # Journey reminders
    #   Native mail.activity records, so they surface in the systray clock,
    #   the "My Activities" list and the kanban colour dots. They go to the
    #   lead's salesperson only - no manager escalation, by design.
    # ==================================================================
    # Stages that end the conversation: reaching any of them clears whatever
    # reminders are still open, so nobody chases a dead lead.
    _JOURNEY_CLOSING_STAGES = (
        'crm.stage_lead4',                          # Won
        'crm_extended_rk.stage_lost',               # Lost
        'crm_extended_rk.stage_not_qualified',      # Not Qualified
    )

    _JOURNEY_ACTIVITY_XMLIDS = (
        'crm_extended_rk.activity_send_discovery',
        'crm_extended_rk.activity_chase_discovery',
        'crm_extended_rk.activity_share_proposal',
        'crm_extended_rk.activity_chase_feedback',
        'crm_extended_rk.activity_client_followup',
        'crm_extended_rk.activity_client_update',
    )

    @api.model
    def _journey_setting(self, key, default):
        """Read one reminder setting, falling back to the shipped default if
        it was never written or somebody blanked it in Settings."""
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'crm_extended_rk.%s' % key)
        if raw in (None, False, ''):
            return default
        if isinstance(default, bool):
            return str(raw).strip().lower() in ('1', 'true', 'yes')
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    @api.model
    def _journey_reminders_go_live(self):
        """The cut-off date. Leads created before it never get reminders.

        This is the whole reason a 148-lead backlog does not detonate on the
        team the day this is switched on: the switch stamps the date, and
        everything older stays quiet.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'crm_extended_rk.journey_reminders_start_date')
        return fields.Date.to_date(raw) if raw else False

    def _journey_reminders_allowed(self):
        """Which leads in self may receive an automatic reminder right now."""
        if not self._journey_setting('journey_reminders_active', False):
            return self.browse()
        go_live = self._journey_reminders_go_live()
        closing_stages = self.env['crm.stage'].browse([
            stage.id for stage in (
                self.env.ref(xmlid, raise_if_not_found=False)
                for xmlid in self._JOURNEY_CLOSING_STAGES)
            if stage
        ])

        def eligible(lead):
            if not lead.active or not lead.user_id:
                return False          # nobody to remind
            if lead.stage_id in closing_stages:
                return False          # conversation is over
            if go_live and lead.create_date and lead.create_date.date() < go_live:
                return False          # pre-existing backlog: leave it alone
            return True

        return self.filtered(eligible)

    @api.model
    def _journey_manager_users(self):
        """Sales Managers, who receive a tracking copy of every reminder.

        Identified by the Sales = Administrator access level
        (`sales_team.group_sale_manager`) - NOT by the Sales Team's leader
        field, which is empty on this database and would route to nobody.
        Promoting someone to Administrator picks them up automatically from
        their next reminder onward.
        """
        group = self.env.ref('sales_team.group_sale_manager', raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        return self.env['res.users'].search([
            ('groups_id', 'in', group.id),
            ('active', '=', True),
            ('share', '=', False),
        ])

    def _schedule_journey_reminder(self, act_type_xmlid, delay_days, summary,
                                   note=''):
        """Put one reminder on each eligible lead.

        The salesperson gets the reminder to act on; every Sales Manager gets
        a tracking copy of the same thing, so the pipeline can be supervised
        without opening each lead. Nobody gets two copies, and a manager who
        happens to own the lead gets the salesperson's copy only.

        Deduplication is per user, not per lead: an existing reminder for the
        salesperson must not stop a manager's copy being created.
        """
        leads = self._journey_reminders_allowed()
        if not leads:
            return
        act_type = self.env.ref(act_type_xmlid, raise_if_not_found=False)
        if not act_type:
            return
        deadline = fields.Date.context_today(self) + timedelta(days=int(delay_days))
        managers = self._journey_manager_users()
        for lead in leads:
            existing_users = lead.activity_ids.filtered(
                lambda a: a.activity_type_id == act_type).mapped('user_id')
            for user in (lead.user_id | managers) - existing_users:
                if user == lead.user_id:
                    user_summary, user_note = summary, note
                else:
                    # A manager's copy is labelled so their own activity list
                    # stays readable, and names who is actually responsible.
                    user_summary = _("Tracking: %s") % summary
                    user_note = _(
                        "Oversight copy for Sales Managers. %(owner)s is "
                        "responsible for this lead.\n\n%(note)s"
                    ) % {'owner': lead.user_id.name or _("Nobody"), 'note': note}
                # sudo: a salesperson may trigger an event on a lead owned by a
                # colleague (an approved quotation, a returned form), and
                # crm.crm_rule_personal_lead would refuse the write.
                lead.sudo().activity_schedule(
                    act_type_xmlid,
                    date_deadline=deadline,
                    summary=user_summary,
                    note=user_note,
                    user_id=user.id)

    def _clear_journey_reminders(self, act_type_xmlids=None):
        """Drop open reminders - because the thing they asked for just happened."""
        xmlids = act_type_xmlids or list(self._JOURNEY_ACTIVITY_XMLIDS)
        if self:
            self.sudo().activity_unlink(xmlids)

    # -- Triggers -------------------------------------------------------
    def _journey_on_lead_created(self):
        self._schedule_journey_reminder(
            'crm_extended_rk.activity_send_discovery',
            self._journey_setting('delay_send_discovery', 1),
            _("Send the discovery form"),
            _("This lead has just been created. Send the client the discovery "
              "form for the service they are asking about."))

    def _journey_on_discovery_sent(self):
        self._clear_journey_reminders(['crm_extended_rk.activity_send_discovery'])
        self._schedule_journey_reminder(
            'crm_extended_rk.activity_chase_discovery',
            self._journey_setting('delay_chase_discovery', 3),
            _("Chase the discovery form"),
            _("The discovery form was sent but the client has not returned it "
              "yet. Give them a call."))

    def _journey_on_discovery_received(self):
        self._clear_journey_reminders(['crm_extended_rk.activity_chase_discovery'])
        self._schedule_journey_reminder(
            'crm_extended_rk.activity_share_proposal',
            self._journey_setting('delay_prepare_proposal', 2),
            _("Prepare and share the proposal"),
            _("The client has returned the discovery form. Prepare the "
              "quotation and share it with them."))

    def _journey_on_proposal_sent(self):
        self._clear_journey_reminders(['crm_extended_rk.activity_share_proposal'])
        self._schedule_journey_reminder(
            'crm_extended_rk.activity_chase_feedback',
            self._journey_setting('delay_chase_feedback', 3),
            _("Chase the client for feedback"),
            _("The proposal has been shared. Follow up for the client's "
              "decision or comments."))

    @api.model
    def _cron_nudge_stale_leads(self):
        """Every open lead, in every stage, gets an alert if nothing has
        happened on it for the configured number of hours (48 by default).

        "Nothing has happened" means no journey event AND no reminder already
        waiting. A lead that already has an open prompt is not nudged again -
        that prompt is the alert, and duplicating it would bury the team
        rather than help them.

        Once the salesperson deals with it, the clock restarts: if the lead
        goes quiet for another 48 hours it is alerted again.
        """
        if not self._journey_setting('journey_reminders_active', False):
            return 0
        nudge_hours = int(self._journey_setting('nudge_hours', 48))
        cutoff = fields.Datetime.now() - timedelta(hours=nudge_hours)
        candidates = self.search([('active', '=', True)])._journey_reminders_allowed()
        if not candidates:
            return 0

        recent = self.env['crm.lead.event'].sudo().search([
            ('lead_id', 'in', candidates.ids),
            ('event_date', '>=', cutoff),
        ])
        busy_lead_ids = set(recent.mapped('lead_id').ids)
        stale = candidates.filtered(
            lambda lead: lead.id not in busy_lead_ids and not lead.activity_ids)

        # Grouped by stage so the alert can name where the lead is stuck,
        # which is the whole point of running this across every stage.
        nudged = 0
        for stage, leads in stale.grouped('stage_id').items():
            leads._schedule_journey_reminder(
                'crm_extended_rk.activity_client_followup', 0,
                _("Follow up - %(hours)sh with no activity in %(stage)s") % {
                    'hours': nudge_hours, 'stage': stage.name or _("this stage")},
                _("This lead has been sitting in %(stage)s for over "
                  "%(hours)s hours with nothing recorded against it. Contact "
                  "the client, or move it out of the pipeline.") % {
                    'stage': stage.name or _("its current stage"),
                    'hours': nudge_hours})
            nudged += len(leads)
        return nudged

    @api.model
    def _apply_journey_cron_schedule(self):
        """Keep the sweep frequent enough to honour a 48-hour promise.

        A daily cron would let a lead sit up to 24 hours past the deadline
        before anyone hears about it. Only rewrites the shipped default, so
        an interval the user has tuned by hand is left alone.
        """
        cron = self.env.ref('crm_extended_rk.ir_cron_journey_stale_leads',
                            raise_if_not_found=False)
        if cron and cron.interval_type == 'days' and cron.interval_number == 1:
            cron.sudo().write({'interval_type': 'hours', 'interval_number': 2})
        return True
