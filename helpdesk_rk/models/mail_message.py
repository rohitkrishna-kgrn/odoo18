from odoo import models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def _message_fetch(self, domain, **kwargs):
        targets_ticket = any(
            isinstance(d, (list, tuple)) and len(d) == 3
            and d[0] == 'model' and d[1] == '=' and d[2] == 'helpdesk_rk.ticket'
            for d in domain
        )
        if targets_ticket:
            chat_subtype = self.env.ref('helpdesk_rk.mt_ticket_chat', raise_if_not_found=False)
            if chat_subtype:
                domain = domain + [('subtype_id', '!=', chat_subtype.id)]
        return super()._message_fetch(domain, **kwargs)
