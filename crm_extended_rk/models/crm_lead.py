# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .crm_tag import APPROVED_TAG_DOMAIN, TAG_SYNC_CTX, log_tag_change
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

    # Ticked = the salesperson fills the form in for the client (answers
    # gathered over a call/meeting), so the link is emailed to the salesperson
    # and the client is never contacted for that submission.
    discovery_on_behalf = fields.Boolean(
        string='On Behalf of', tracking=True,
        help="Tick to send the discovery form link to the salesperson instead "
             "of the client, so it can be filled in on the client's behalf. "
             "The client receives nothing.")

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

    # Free-text reason captured by the "Mark Lost" popup (which no longer
    # offers the crm.lost.reason dropdown). The legacy lost_reason_id is kept
    # for opportunities lost before this change but is never written to now.
    lost_reason_note = fields.Char(string='Lost Reason', copy=False, tracking=True)

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
    def _discovery_recipient(self, on_behalf):
        """Who a discovery form link is emailed to, as (email, name).

        Normally the client. When the form is filled in on the client's
        behalf, it is the assigned salesperson instead - the client is not
        emailed at all. Raises if that recipient has no address, so nothing
        is created or logged for a send that cannot happen.
        """
        self.ensure_one()
        if on_behalf:
            user = self.user_id
            if not user:
                raise UserError(_(
                    "\"On Behalf of\" is ticked, so the discovery form has to go to "
                    "the salesperson - but no salesperson is assigned to this "
                    "pipeline. Assign one, or untick \"On Behalf of\" to send the "
                    "form to the client."))
            if not user.email:
                raise UserError(_(
                    "\"On Behalf of\" is ticked, so the discovery form has to go to "
                    "the salesperson - but %s has no email address on their user "
                    "record. Add one, or untick \"On Behalf of\" to send the form "
                    "to the client.") % user.name)
            return (user.email, user.name)
        if not self.email_from:
            raise UserError(_(
                "Please set the email address on this pipeline before sending the "
                "discovery form."))
        return (self.email_from, self.contact_name or self.partner_name or '')

    def action_send_discovery_form(self):
        """Header button: create and send a new discovery form submission of
        whichever type is currently selected. Can be clicked repeatedly to
        send further forms (same or different type) over the opportunity's
        lifetime."""
        self.ensure_one()
        if not self.discovery_form_type:
            raise UserError(_("Please select which Discovery Form to send first."))
        # Validate before creating anything: raises when the recipient (client,
        # or salesperson when sending on the client's behalf) has no address.
        on_behalf = self.discovery_on_behalf
        email = self._discovery_recipient(on_behalf)[0]

        submission = self.env['crm.lead.discovery.form'].create({
            'lead_id': self.id,
            'form_type': self.discovery_form_type,
            'on_behalf': on_behalf,
        })
        submission.action_send()

        if on_behalf:
            message = _(
                "The %(form)s discovery form link has been sent to %(email)s to be "
                "filled in on the client's behalf. The client was not emailed."
            ) % {'form': submission.form_label, 'email': email}
        else:
            message = _(
                "The %(form)s discovery form link has been sent to %(email)s."
            ) % {'form': submission.form_label, 'email': email}

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _("Discovery Form Sent"),
                'message': message,
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

    def _tags_from_partner(self):
        """Carry the tags already on the contact onto the lead.

        Purely additive, and only from a contact that carries CRM tags - the
        classification usually exists on the client long before the
        opportunity does, so picking the client should not mean re-typing it.
        """
        for lead in self.filtered('partner_id'):
            missing = lead.partner_id._crm_tags() - lead.tag_ids
            if missing:
                lead.tag_ids = [(4, tag.id) for tag in missing]

    @api.onchange('partner_id')
    def _onchange_partner_id_tags(self):
        """Picking the client on the form (or the quick-create popup, where
        Tags is mandatory) fills its tags in straight away."""
        for lead in self.filtered('partner_id'):
            # A recordset, not a command list: commands on an x2many in an
            # onchange drop rows silently.
            lead.tag_ids |= lead.partner_id._crm_tags()

    @api.model_create_multi
    def create(self, vals_list):
        leads = super().create(vals_list)
        for lead in leads:
            lead._log_journey_event(
                'lead_created',
                _("Lead created"),
                note=_("Source: %s") % (lead.source_id.name or _("not set")))
        # Tags travel between the lead, its contact and its quotations - see
        # res_partner._sync_crm_tags.
        leads._tags_from_partner()
        self.env['res.partner']._apply_crm_tags_from(leads.filtered('tag_ids'), mirror=False)
        return leads

    def write(self, vals):
        # Capture the old stage before super(), which overwrites it.
        previous_stages = {}
        if 'stage_id' in vals:
            previous_stages = {lead.id: lead.stage_id for lead in self}
        # The sync writes its own chatter note, saying where the tags came from.
        tags_before = ({lead.id: lead.tag_ids for lead in self}
                       if 'tag_ids' in vals and not self.env.context.get(TAG_SYNC_CTX) else {})
        res = super().write(vals)
        for lead in self:
            if lead.id in tags_before:
                log_tag_change(lead, tags_before[lead.id], lead.tag_ids)
        if 'tag_ids' in vals or 'partner_id' in vals:
            self.env['res.partner']._apply_crm_tags_from(self)
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

