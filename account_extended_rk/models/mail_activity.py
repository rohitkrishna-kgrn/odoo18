from odoo import models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    def _action_done(self, feedback=False, attachment_ids=None):
        """Carry the feedback text through to the follow-up log.

        Core renders the feedback into a QWeb body ("Call done: ... Feedback:
        ...") and keeps nothing structured, so account.move.message_post would
        have to scrape it back out of translated HTML. Passing it down the
        context instead is exact. Set on self.env, which the sudo() recordset
        core builds for the message_post inherits.
        """
        return super(
            MailActivity,
            self.with_context(ar_followup_feedback=feedback or ''),
        )._action_done(feedback=feedback, attachment_ids=attachment_ids)
