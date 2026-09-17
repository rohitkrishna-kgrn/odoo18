# -*- coding: utf-8 -*-
from odoo import _, fields, models


class MailActivityType(models.Model):
    _inherit = 'mail.activity.type'

    # Lets each activity type say what it means in journey terms, so ticking
    # off "Chase Client Feedback" lands in the log as a feedback event rather
    # than a generic "activity completed". Data-driven on purpose: new types
    # can be mapped from the UI without a code change.
    crm_journey_event_type = fields.Selection(
        selection=lambda self: self.env['crm.lead.event']._fields['event_type'].selection,
        string='Journey Event',
        help="When an activity of this type is marked done on an opportunity, "
             "record it in the lead journey under this heading. "
             "Leave empty to log it as a plain completed activity.")


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _action_done(self, feedback=False, attachment_ids=None):
        Lead = self.env['crm.lead']

        # Collect everything needed BEFORE super(): _action_done unlinks the
        # activities, so self is unusable afterwards.
        completed = []
        for activity in self:
            if activity.res_model != 'crm.lead' or not activity.res_id:
                continue
            lead = Lead.browse(activity.res_id).exists()
            if not lead:
                continue
            completed.append({
                'lead': lead,
                'event_type': activity.activity_type_id.crm_journey_event_type or 'activity_done',
                'type_name': activity.activity_type_id.name or _("Activity"),
                'summary': activity.summary or '',
            })

        res = super()._action_done(feedback=feedback, attachment_ids=attachment_ids)

        for item in completed:
            item['lead']._log_journey_event(
                item['event_type'],
                _("%(type)s completed%(detail)s") % {
                    'type': item['type_name'],
                    'detail': ": %s" % item['summary'] if item['summary'] else '',
                },
                note=feedback or False,
                from_activity=True)
        return res
