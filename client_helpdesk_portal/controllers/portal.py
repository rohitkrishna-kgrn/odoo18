import base64
import logging
from datetime import datetime
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    'image/jpeg', 'image/png', 'image/gif', 'image/webp',
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain',
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file

SESSION_KEY = 'helpdesk_submission'


class HelpdeskPortalController(http.Controller):

    @http.route('/helpdesk/submit', type='http', auth='public', website=True, csrf=True)
    def helpdesk_form(self, **kwargs):
        response = request.render(
            'client_helpdesk_portal.helpdesk_submission_form',
            {'error': {}, 'form_data': {}, 'success': False},
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @http.route('/helpdesk/submit/post', type='http', auth='public',
                website=True, csrf=True, methods=['POST'])
    def helpdesk_form_submit(self, **post):
        attachments = request.httprequest.files.getlist('attachment')

        errors = self._validate_form(post, attachments)
        if errors:
            return request.render(
                'client_helpdesk_portal.helpdesk_submission_form',
                {'error': errors, 'form_data': post, 'success': False},
            )

        ticket = self._create_ticket(post, attachments)
        if not ticket:
            return request.render(
                'client_helpdesk_portal.helpdesk_submission_form',
                {
                    'error': {'general': 'An unexpected error occurred. Please try again.'},
                    'form_data': post,
                    'success': False,
                },
            )

        # PRG: store in session, then redirect so back-button shows a fresh form
        request.session[SESSION_KEY] = {
            'ticket_number': ticket.ticket_number,
            'ticket_id': ticket.id,
            'subject': ticket.subject,
            'client_name': ticket.client_name,
            'email': ticket.email,
            'created_date': ticket.created_date.isoformat() if ticket.created_date else '',
        }
        return request.redirect('/helpdesk/submit/success')

    @http.route('/helpdesk/submit/success', type='http', auth='public', website=True)
    def helpdesk_success(self, **kwargs):
        data = request.session.pop(SESSION_KEY, None)
        if not data:
            # No session means they refreshed or navigated here directly — send to form
            return request.redirect('/helpdesk/submit')

        created_date = None
        if data.get('created_date'):
            try:
                created_date = datetime.fromisoformat(data['created_date'])
            except (ValueError, TypeError):
                pass

        return request.render(
            'client_helpdesk_portal.helpdesk_submission_success',
            {
                'ticket_number': data['ticket_number'],
                'ticket_id': data['ticket_id'],
                'subject': data['subject'],
                'client_name': data['client_name'],
                'email': data['email'],
                'created_date': created_date,
            },
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Validation
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_form(self, post, attachments):
        errors = {}
        required = {
            'client_name': 'Client Name',
            'email': 'Email Address',
            'phone': 'Phone Number',
            'request_type': 'Request Type',
            'subject': 'Subject',
            'description': 'Description',
        }
        for field, label in required.items():
            if not post.get(field, '').strip():
                errors[field] = f'{label} is required.'

        email = post.get('email', '').strip()
        if email and '@' not in email:
            errors['email'] = 'Please enter a valid email address.'

        phone = post.get('phone', '').strip()
        if phone and len(phone) < 7:
            errors['phone'] = 'Please enter a valid phone number.'

        valid_types = {'issue', 'complaint', 'other'}
        if post.get('request_type') not in valid_types:
            errors['request_type'] = 'Invalid request type selected.'

        valid_priorities = {'0', '1', '2'}
        priority = post.get('priority', '0')
        if priority not in valid_priorities:
            errors['priority'] = 'Invalid priority selected.'

        att_errors = []
        for att in attachments:
            if not att or not att.filename:
                continue
            if att.content_type not in ALLOWED_MIME_TYPES:
                att_errors.append(f'"{att.filename}" — file type not allowed.')
                continue
            content = att.read()
            att.seek(0)
            if len(content) > MAX_FILE_SIZE:
                att_errors.append(f'"{att.filename}" exceeds the 10 MB limit.')

        if att_errors:
            errors['attachment'] = ' '.join(att_errors)

        return errors

    # ─────────────────────────────────────────────────────────────────────────
    # Ticket creation
    # ─────────────────────────────────────────────────────────────────────────

    def _create_ticket(self, post, attachments):
        # Step 1: create the ticket — return None on failure so caller shows error page
        try:
            Ticket = request.env['client.helpdesk.ticket'].sudo()
            vals = {
                'client_name': post.get('client_name', '').strip(),
                'company_name': post.get('company_name', '').strip() or False,
                'email': post.get('email', '').strip(),
                'phone': post.get('phone', '').strip(),
                'request_type': post.get('request_type', 'issue'),
                'subject': post.get('subject', '').strip(),
                'description': post.get('description', '').strip(),
                'priority': post.get('priority', '0'),
                'reference_number': post.get('reference_number', '').strip() or False,
            }
            ticket = Ticket.create(vals)
        except Exception as exc:
            _logger.error('Failed to create helpdesk ticket: %s', exc, exc_info=True)
            return None

        # Step 2: persist attachments — failures are logged but never block the ticket
        self._save_attachments(ticket, attachments)

        return ticket

    def _save_attachments(self, ticket, attachments):
        """Create ir.attachment records for each uploaded file and link them to the ticket."""
        try:
            IrAttachment = request.env['ir.attachment'].sudo()
            att_ids = []
            for att in attachments:
                if not att or not att.filename:
                    continue
                content = att.read()
                if not content:
                    continue
                rec = IrAttachment.create({
                    'name': att.filename,
                    'datas': base64.b64encode(content).decode('utf-8'),
                    'res_model': 'client.helpdesk.ticket',
                    'res_id': ticket.id,
                    'mimetype': att.content_type,
                })
                att_ids.append(rec.id)
            if att_ids:
                ticket.sudo().write({'portal_attachment_ids': [(4, aid) for aid in att_ids]})
        except Exception as exc:
            _logger.error(
                'Failed to save attachments for ticket %s: %s',
                ticket.ticket_number, exc, exc_info=True,
            )
