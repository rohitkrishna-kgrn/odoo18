import logging

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import str2bool
from werkzeug.exceptions import NotFound

_logger = logging.getLogger(__name__)


class HelpdeskChatController(http.Controller):

    def _get_chat_ticket(self, ticket_id):
        return request.env['helpdesk_rk.ticket'].browse(int(ticket_id)).exists()

    @http.route('/helpdesk_rk/chat/upload_attachment', type='http', auth='user', methods=['POST'], csrf=True)
    def upload_attachment(self, ticket_id, ufile, **kwargs):
        ticket = self._get_chat_ticket(ticket_id)
        error = None
        data = None
        if not ticket:
            error = "Ticket not found."
        elif not ticket._can_post_chat_message():
            error = "You are not allowed to upload attachments on this ticket."
        else:
            content = ufile.read()
            if not content:
                return request.make_json_response({'data': None, 'error': "The file is empty."})
            try:
                # Created as the acting user, not through sudo(): both
                # message_post() and _link_pending_chat_attachments only adopt
                # a pending attachment whose create_uid is the person posting,
                # so anything owned by someone else is silently dropped from
                # the message. A plain internal user may create an
                # ir.attachment parked on the composer (res_id 0), so sudo
                # buys nothing here and would only blur who owns the file.
                attachment = request.env['ir.attachment'].create({
                    'name': ufile.filename,
                    'raw': content,
                    'res_model': 'mail.compose.message',
                    'res_id': 0,
                })
            except (AccessError, UserError) as exc:
                _logger.warning("Helpdesk chat upload refused on ticket %s: %s", ticket.id, exc)
                return request.make_json_response({'data': None, 'error': str(exc)})
            data = {
                'id': attachment.id,
                'name': attachment.name,
                'mimetype': attachment.mimetype,
                'size': attachment.file_size,
            }
        return request.make_json_response({'data': data, 'error': error})

    @http.route('/helpdesk_rk/chat/discard_attachment', type='json', auth='user', methods=['POST'])
    def discard_attachment(self, attachment_id):
        """Drop a file the user attached and then removed before sending, so
        unsent uploads don't pile up in the filestore. Only ever touches an
        attachment this user uploaded and that is still unposted."""
        attachment = request.env['ir.attachment'].sudo().browse(int(attachment_id)).exists()
        if (attachment and attachment.res_model == 'mail.compose.message'
                and not attachment.res_id and attachment.create_uid.id == request.env.uid):
            attachment.unlink()
            return True
        return False

    @http.route('/helpdesk_rk/chat/attachment/<int:attachment_id>', type='http', auth='user')
    def chat_attachment(self, attachment_id, download=False, **kwargs):
        """Serve a file shared in a ticket conversation to *either* party.

        Read access on ir.attachment follows the record it hangs off, which
        makes downloads on the other side fragile as soon as a record rule
        narrows the ticket down. So look the file up in sudo and decide here
        who may have it: the creator, the assigned agent, or support/admin.
        """
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != 'helpdesk_rk.ticket' or not attachment.res_id:
            raise NotFound()
        ticket = request.env['helpdesk_rk.ticket'].sudo().browse(attachment.res_id).exists()
        if not ticket or not ticket._can_access_chat(request.env.user):
            raise NotFound()
        stream = request.env['ir.binary']._get_stream_from(
            attachment, 'raw', filename=attachment.name, filename_field='name',
        )
        return stream.get_response(as_attachment=str2bool(download or 'false'))
