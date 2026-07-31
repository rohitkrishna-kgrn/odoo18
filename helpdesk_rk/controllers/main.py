from odoo import http
from odoo.http import request


class HelpdeskChatController(http.Controller):

    @http.route('/helpdesk_rk/chat/upload_attachment', type='http', auth='user', methods=['POST'], csrf=True)
    def upload_attachment(self, ticket_id, ufile, **kwargs):
        ticket = request.env['helpdesk_rk.ticket'].browse(int(ticket_id)).exists()
        error = None
        data = None
        if not ticket:
            error = "Ticket not found."
        elif not ticket._can_post_chat_message():
            error = "You are not allowed to upload attachments on this ticket."
        else:
            attachment = request.env['ir.attachment'].sudo().create({
                'name': ufile.filename,
                'raw': ufile.read(),
                'res_model': 'mail.compose.message',
                'res_id': 0,
            })
            data = {
                'id': attachment.id,
                'name': attachment.name,
                'mimetype': attachment.mimetype,
            }
        return request.make_json_response({'data': data, 'error': error})
