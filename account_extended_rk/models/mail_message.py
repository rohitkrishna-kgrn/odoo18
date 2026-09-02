from odoo import models
from odoo.tools import html2plaintext


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def write(self, vals):
        """Keep an edited Log note and its follow-up row in step.

        The chatter is the record of truth; a follow-up row is a projection of
        it. Editing a note and leaving the AR report quoting the old wording
        would make the report evidence of something nobody said.
        """
        logs = self.env['account.invoice.followup.log']
        if 'body' in vals and self.ids:
            logs = logs.sudo().search([
                ('message_id', 'in', self.ids),
                # An activity follow-up's response is the feedback the user
                # typed, not the rendered body: re-deriving it here would
                # overwrite it with the template boilerplate.
                ('source', '=', 'note'),
            ])
        # The old body has to be read before super() overwrites it, so a
        # method AR corrected by hand can be told apart from one still sitting
        # at whatever the note's wording implied.
        was_derived = {
            log.id: log.method == logs._method_from_text(
                ' '.join(html2plaintext(log.message_id.body or '').split()))
            for log in logs
        }

        res = super().write(vals)

        for log in logs:
            text = ' '.join(html2plaintext(log.message_id.body or '').split())
            log_vals = {'response': text or False}
            if was_derived.get(log.id):
                log_vals['method'] = logs._method_from_text(text)
            log.write(log_vals)
        return res
