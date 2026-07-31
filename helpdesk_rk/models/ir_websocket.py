import re

from odoo import models

TICKET_CHAT_CHANNEL_RE = re.compile(r'helpdesk_rk\.ticket_chat_(\d+)')


class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        for channel in list(channels):
            if isinstance(channel, str):
                match = TICKET_CHAT_CHANNEL_RE.fullmatch(channel)
                if match:
                    channels.remove(channel)
                    ticket_id = int(match.group(1))
                    if self.env['helpdesk_rk.ticket'].search_count([('id', '=', ticket_id)]):
                        channels.append(channel)
        return super()._build_bus_channel_list(channels)
