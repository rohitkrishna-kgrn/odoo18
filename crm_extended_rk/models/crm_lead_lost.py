# -*- coding: utf-8 -*-
from markupsafe import Markup

from odoo import _, fields, models
from odoo.tools.mail import is_html_empty


class CrmLeadLost(models.TransientModel):
    _inherit = 'crm.lead.lost'

    # Free-text replacement for the standard crm.lost.reason dropdown in the
    # "Mark Lost" popup: the salesperson types the reason instead of picking
    # (or quick-creating) a crm.lost.reason record. It is stored verbatim on
    # the lead as crm.lead.lost_reason_note; lost_reason_id is left empty.
    lost_reason_text = fields.Char('Lost Reason')

    def action_lost_reason_apply(self):
        """Mark the lead(s) lost, recording the typed reason as free text."""
        self.ensure_one()
        reason = (self.lost_reason_text or '').strip()

        if reason:
            self.lead_ids.lost_reason_note = reason

        # Keep the standard "Lost Comment" chatter entry, and log the typed
        # reason alongside it so the chatter carries the full picture.
        log_parts = []
        if reason:
            log_parts.append(
                Markup('<div style="margin-bottom: 4px;"><p>%s: %s</p></div>') % (
                    _('Lost Reason'), reason))
        if not is_html_empty(self.lost_feedback):
            log_parts.append(
                Markup('<div style="margin-bottom: 4px;"><p>%s:</p>%s<br /></div>') % (
                    _('Lost Comment'), self.lost_feedback))
        if log_parts:
            self.lead_ids._track_set_log_message(Markup('').join(log_parts))

        return self.lead_ids.action_set_lost()
