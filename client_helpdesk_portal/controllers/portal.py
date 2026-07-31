import base64
import logging
from datetime import datetime, timedelta
from urllib.parse import urlencode
from odoo import http, fields
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

GST_OFFSET = timedelta(hours=4)

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
REOPEN_SESSION_KEY = 'helpdesk_reopen'
TRACK_SESSION_KEY = 'helpdesk_verified_tickets'
DASHBOARD_SESSION_KEY = 'helpdesk_dashboard_email'

STAGE_BADGE_CLASS = {
    'New': 'hd-stage-new',
    'Under Review': 'hd-stage-review',
    'In Progress': 'hd-stage-progress',
    'Waiting for Client': 'hd-stage-waiting',
    'Resolved': 'hd-stage-resolved',
    'Closed': 'hd-stage-closed',
    'Reopened': 'hd-stage-reopened',
}


class HelpdeskPortalController(http.Controller):

    def _get_top_level_team_name(self, department):
        """Walk up department.parent_id to the top-level team — e.g. "AUDIT
        & ASSURANCE - COIMBATORE" (a sub-team/location under "AUDIT &
        ASSURANCE") groups under "AUDIT & ASSURANCE", not its own full
        name."""
        if not department:
            return 'General'
        visited = set()
        while department.parent_id and department.id not in visited:
            visited.add(department.id)
            department = department.parent_id
        return department.name

    def _get_active_employees(self):
        """Employees with Select Access enabled in Helpdesk Portal Users
        (Configuration → Helpdesk Portal Users), queried fresh on every
        request and grouped by top-level team for the dropdown's
        <optgroup> sections. Excludes employees with no linked Odoo user
        account — a ticket's "Assigned To" is a res.users, so picking one
        of those would otherwise silently fall back to the Helpdesk Admin
        (see create()). Select Access is the sole eligibility criterion
        otherwise — no active-login requirement, matching
        client.helpdesk.ticket._get_assignable_users()."""
        portal_users = request.env['client.helpdesk.portal.user'].sudo().search(
            [('active', '=', True), ('select_access', '=', True),
             ('employee_id.active', '=', True),
             ('employee_id.user_id', '!=', False),
             ('employee_id.company_id', 'in', [request.env.company.id, False])],
        )
        teams = {}
        for pu in portal_users.sorted(lambda p: p.employee_id.name or ''):
            team_name = self._get_top_level_team_name(pu.department_id)
            teams.setdefault(team_name, []).append({
                'id': pu.employee_id.id,
                'name': pu.employee_id.name,
            })
        return [
            {'team': team_name, 'employees': teams[team_name]}
            for team_name in sorted(teams)
        ]

    def _is_selectable_employee(self, employee):
        """Server-side guard mirroring the dropdown filter — a POST can't
        request a handler that isn't select_access-enabled and linked to a
        real user account, even if the employee id itself is valid/active."""
        return bool(employee.user_id) and bool(
            request.env['client.helpdesk.portal.user'].sudo().search_count([
                ('employee_id', '=', employee.id),
                ('active', '=', True),
                ('select_access', '=', True),
            ])
        )

    @http.route('/helpdesk/submit', type='http', auth='public', website=True, csrf=True)
    def helpdesk_form(self, **kwargs):
        response = request.render(
            'client_helpdesk_portal.helpdesk_submission_form',
            {'error': {}, 'form_data': {}, 'success': False, 'employees': self._get_active_employees()},
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
                {'error': errors, 'form_data': post, 'success': False,
                 'employees': self._get_active_employees()},
            )

        ticket = self._create_ticket(post, attachments)
        if not ticket:
            return request.render(
                'client_helpdesk_portal.helpdesk_submission_form',
                {
                    'error': {'general': 'An unexpected error occurred. Please try again.'},
                    'form_data': post,
                    'success': False,
                    'employees': self._get_active_employees(),
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
                created_date = datetime.fromisoformat(data['created_date']) + GST_OFFSET
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
            'company_name': 'Company Name',
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
        request_type = post.get('request_type')
        if request_type not in valid_types:
            errors['request_type'] = 'Invalid request type selected.'

        valid_priorities = {'0', '1', '2'}
        priority = post.get('priority', '0')
        if priority not in valid_priorities:
            errors['priority'] = 'Invalid priority selected.'

        requested_employee_id = post.get('requested_employee_id', '').strip()
        if requested_employee_id:
            try:
                employee = request.env['hr.employee'].sudo().browse(int(requested_employee_id))
            except ValueError:
                employee = request.env['hr.employee']
            if (not employee.exists() or not employee.active
                    or not self._is_selectable_employee(employee)):
                errors['requested_employee_id'] = 'Please select a valid handler.'

        valid_attachments = [att for att in attachments if att and att.filename]

        att_errors = []
        if request_type == 'issue' and not valid_attachments:
            att_errors.append('Attachment is mandatory for Technical Issue tickets.')
        for att in valid_attachments:
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
                'requested_employee_id': int(post['requested_employee_id'])
                    if post.get('requested_employee_id', '').strip() else False,
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

    # ─────────────────────────────────────────────────────────────────────────
    # Reopen ticket
    # ─────────────────────────────────────────────────────────────────────────

    @http.route('/helpdesk/reopen', type='http', auth='public', website=True, csrf=True)
    def helpdesk_reopen_form(self, **kwargs):
        response = request.render(
            'client_helpdesk_portal.helpdesk_reopen_form',
            {'error': {}, 'form_data': {}},
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @http.route('/helpdesk/reopen/post', type='http', auth='public',
                website=True, csrf=True, methods=['POST'])
    def helpdesk_reopen_submit(self, **post):
        errors, ticket = self._validate_reopen_form(post)
        if errors:
            return request.render(
                'client_helpdesk_portal.helpdesk_reopen_form',
                {'error': errors, 'form_data': post},
            )

        reason = post.get('reason', '').strip()
        try:
            ticket.sudo().action_reopen_by_client(reason)
        except Exception as exc:
            _logger.error('Failed to reopen ticket %s: %s', ticket.ticket_number, exc, exc_info=True)
            return request.render(
                'client_helpdesk_portal.helpdesk_reopen_form',
                {'error': {'general': str(exc) or 'Unable to reopen this ticket. Please try again.'},
                 'form_data': post},
            )

        # Reopening already proved ticket_number+email ownership — extend
        # that proof to the Track session too so the "Track Ticket" button
        # on the success page works without asking the client to repeat it.
        self._mark_ticket_verified(ticket.ticket_number)

        request.session[REOPEN_SESSION_KEY] = {
            'ticket_number': ticket.ticket_number,
            'subject': ticket.subject,
            'client_name': ticket.client_name,
            'created_date': ticket.created_date.isoformat() if ticket.created_date else '',
            'stage_name': ticket.stage_id.name,
            'assigned_to': ticket.user_id.name or 'Helpdesk Admin',
            'reason': reason,
        }
        return request.redirect('/helpdesk/reopen/success')

    @http.route('/helpdesk/reopen/success', type='http', auth='public', website=True)
    def helpdesk_reopen_success(self, **kwargs):
        data = request.session.pop(REOPEN_SESSION_KEY, None)
        if not data:
            return request.redirect('/helpdesk/reopen')

        created_date = None
        if data.get('created_date'):
            try:
                created_date = datetime.fromisoformat(data['created_date']) + GST_OFFSET
            except (ValueError, TypeError):
                pass
        return request.render(
            'client_helpdesk_portal.helpdesk_reopen_success',
            {
                'ticket_number': data['ticket_number'],
                'subject': data['subject'],
                'client_name': data['client_name'],
                'created_date': created_date,
                'stage_name': data['stage_name'],
                'assigned_to': data['assigned_to'],
                'reason': data['reason'],
            },
        )

    def _lookup_verified_ticket(self, ticket_number, email):
        """Find a ticket by number and confirm the given email matches our
        records for it — the identity proof shared by the Reopen and Track
        flows (no login exists anywhere in this module). Returns
        (error_message_or_None, ticket_or_None)."""
        ticket = request.env['client.helpdesk.ticket'].sudo().search(
            [('ticket_number', '=', ticket_number)], limit=1,
        )
        if not ticket:
            return 'No ticket was found with that ticket number.', None
        if (ticket.email or '').strip().lower() != email.lower():
            return 'The email address does not match our records for this ticket.', None
        return None, ticket

    def _validate_reopen_form(self, post):
        errors = {}
        ticket_number = post.get('ticket_number', '').strip()
        email = post.get('email', '').strip()
        reason = post.get('reason', '').strip()

        if not ticket_number:
            errors['ticket_number'] = 'Ticket number is required.'
        if not email:
            errors['email'] = 'Email address is required.'
        if not reason:
            errors['reason'] = 'Please tell us why you are reopening this ticket.'

        if errors:
            return errors, None

        error, ticket = self._lookup_verified_ticket(ticket_number, email)
        if error:
            errors['general'] = error
            return errors, None

        if ticket.stage_id.name != 'Closed':
            errors['general'] = 'Only closed tickets can be reopened.'
            return errors, None

        return errors, ticket

    # ─────────────────────────────────────────────────────────────────────────
    # Track ticket
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_track_form(self, post):
        errors = {}
        ticket_number = post.get('ticket_number', '').strip()
        email = post.get('email', '').strip()

        if not ticket_number:
            errors['ticket_number'] = 'Ticket number is required.'
        if not email:
            errors['email'] = 'Email address is required.'
        if errors:
            return errors, None

        error, ticket = self._lookup_verified_ticket(ticket_number, email)
        if error:
            errors['general'] = error
            return errors, None

        return errors, ticket

    def _mark_ticket_verified(self, ticket_number):
        """Remember, for this browser session only, that the visitor proved
        ownership of this ticket number — lets the tracking page be
        revisited/refreshed without re-entering the email every time."""
        verified = list(request.session.get(TRACK_SESSION_KEY) or [])
        if ticket_number not in verified:
            verified.append(ticket_number)
        request.session[TRACK_SESSION_KEY] = verified

    def _is_ticket_verified(self, ticket_number):
        return ticket_number in (request.session.get(TRACK_SESSION_KEY) or [])

    @http.route('/helpdesk/track', type='http', auth='public', website=True, csrf=True)
    def helpdesk_track_form(self, **kwargs):
        ticket_number = (kwargs.get('ticket_number') or '').strip()
        email = (kwargs.get('email') or '').strip()
        errors = {}
        # A link from an email can carry both params — skip straight to the
        # tracking page instead of making the visitor retype anything.
        if ticket_number and email:
            errors, ticket = self._validate_track_form(
                {'ticket_number': ticket_number, 'email': email},
            )
            if not errors:
                self._mark_ticket_verified(ticket.ticket_number)
                return request.redirect(f'/helpdesk/track/{ticket.ticket_number}')

        response = request.render(
            'client_helpdesk_portal.helpdesk_track_form',
            {'error': errors, 'form_data': {'ticket_number': ticket_number, 'email': email}},
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @http.route('/helpdesk/track/post', type='http', auth='public',
                website=True, csrf=True, methods=['POST'])
    def helpdesk_track_submit(self, **post):
        errors, ticket = self._validate_track_form(post)
        if errors:
            return request.render(
                'client_helpdesk_portal.helpdesk_track_form',
                {'error': errors, 'form_data': post},
            )
        self._mark_ticket_verified(ticket.ticket_number)
        return request.redirect(f'/helpdesk/track/{ticket.ticket_number}')

    @http.route('/helpdesk/track/<path:ticket_number>', type='http',
                auth='public', website=True)
    def helpdesk_track_view(self, ticket_number, **kwargs):
        if not self._is_ticket_verified(ticket_number):
            return request.redirect(f'/helpdesk/track?ticket_number={ticket_number}')

        ticket = request.env['client.helpdesk.ticket'].sudo().search(
            [('ticket_number', '=', ticket_number)], limit=1,
        )
        if not ticket:
            return request.redirect('/helpdesk/track')

        request.env['client.helpdesk.notification.log'].sudo().create({
            'ticket_id': ticket.id,
            'event_type': 'portal_view',
            'email_from': '',
            'email_to': ticket.email or '',
            'recipient_label': 'Client',
            'subject': f'Client viewed Track Ticket page for {ticket.ticket_number}',
        })

        resolution_line = ticket.closed_reason_line_ids.filtered(
            lambda l: l.action_type == 'resolve')[:1]
        closed_line = ticket.closed_reason_line_ids.filtered(
            lambda l: l.action_type == 'close')[:1]

        return request.render(
            'client_helpdesk_portal.helpdesk_track_page',
            {
                'ticket': ticket,
                'progress_steps': ticket._track_progress_steps(),
                'resolution_remarks': resolution_line.reason if resolution_line else '',
                'closed_remarks': closed_line.reason if closed_line else '',
            },
        )

    @http.route('/helpdesk/track/<path:ticket_number>/attachment/<int:attachment_id>',
                type='http', auth='public', website=True)
    def helpdesk_track_attachment(self, ticket_number, attachment_id, download=None, **kwargs):
        if not self._is_ticket_verified(ticket_number):
            return request.not_found()

        ticket = request.env['client.helpdesk.ticket'].sudo().search(
            [('ticket_number', '=', ticket_number)], limit=1,
        )
        attachment = request.env['ir.attachment'].sudo().browse(attachment_id).exists()
        if (not ticket or not attachment
                or attachment.res_model != 'client.helpdesk.ticket'
                or attachment.res_id != ticket.id):
            return request.not_found()

        content = base64.b64decode(attachment.datas or b'')
        disposition_type = 'attachment' if download else 'inline'
        headers = [
            ('Content-Type', attachment.mimetype or 'application/octet-stream'),
            ('Content-Length', str(len(content))),
            ('Content-Disposition', content_disposition(attachment.name, disposition_type)),
        ]
        return request.make_response(content, headers)

    # ─────────────────────────────────────────────────────────────────────────
    # Client dashboard — all tickets submitted under one email
    # ─────────────────────────────────────────────────────────────────────────

    DASHBOARD_STAGE_FILTERS = {
        'open': [('is_closed', '=', False)],
        'resolved': [('stage_id.name', '=', 'Resolved')],
        'closed': [('stage_id.name', '=', 'Closed')],
    }

    def _get_dashboard_tickets(self, email, extra_domain=None):
        domain = [('email', '=ilike', email.strip())] + (extra_domain or [])
        # Secondary sort key (id) keeps the order stable/deterministic across
        # reloads even when several tickets share the same created_date —
        # without it, ties can come back in a different order each query.
        return request.env['client.helpdesk.ticket'].sudo().search(
            domain, order='created_date desc, id desc',
        )

    def _parse_dashboard_date(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, '%Y-%m-%d')
        except (ValueError, TypeError):
            return None

    def _dashboard_date_domain(self, date_from, date_to):
        """Client-entered dates are calendar days in GST (the timezone every
        date/time is displayed in elsewhere on this portal) — convert each
        bound to the equivalent UTC instant before filtering created_date,
        which is stored in UTC."""
        domain = []
        start = self._parse_dashboard_date(date_from)
        if start:
            domain.append(('created_date', '>=', start - GST_OFFSET))
        end = self._parse_dashboard_date(date_to)
        if end:
            domain.append(('created_date', '<', end + timedelta(days=1) - GST_OFFSET))
        return domain

    def _build_dashboard_url(self, stage_filter, date_from, date_to):
        params = {}
        if stage_filter and stage_filter != 'all':
            params['filter'] = stage_filter
        if date_from:
            params['date_from'] = date_from
        if date_to:
            params['date_to'] = date_to
        return '/helpdesk/dashboard/view' + ('?' + urlencode(params) if params else '')

    @http.route('/helpdesk/dashboard', type='http', auth='public', website=True, csrf=True)
    def helpdesk_dashboard_login(self, **kwargs):
        if request.session.get(DASHBOARD_SESSION_KEY):
            return request.redirect('/helpdesk/dashboard/view')
        response = request.render(
            'client_helpdesk_portal.helpdesk_dashboard_login',
            {'error': {}, 'form_data': {}},
        )
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @http.route('/helpdesk/dashboard/post', type='http', auth='public',
                website=True, csrf=True, methods=['POST'])
    def helpdesk_dashboard_submit(self, **post):
        email = post.get('email', '').strip()
        errors = {}
        if not email:
            errors['email'] = 'Email address is required.'
        elif '@' not in email:
            errors['email'] = 'Please enter a valid email address.'
        else:
            tickets = self._get_dashboard_tickets(email)
            if not tickets:
                errors['general'] = 'No tickets were found for that email address.'

        if errors:
            return request.render(
                'client_helpdesk_portal.helpdesk_dashboard_login',
                {'error': errors, 'form_data': post},
            )

        request.session[DASHBOARD_SESSION_KEY] = email
        for ticket in self._get_dashboard_tickets(email):
            self._mark_ticket_verified(ticket.ticket_number)
        return request.redirect('/helpdesk/dashboard/view')

    @http.route('/helpdesk/dashboard/view', type='http', auth='public', website=True)
    def helpdesk_dashboard_view(self, **kwargs):
        email = request.session.get(DASHBOARD_SESSION_KEY)
        if not email:
            return request.redirect('/helpdesk/dashboard')

        # Counts and session verification always run against the client's
        # full ticket list — never the filtered subset — so the stat tiles
        # stay accurate and every ticket stays clickable regardless of
        # whichever filter is currently applied.
        all_tickets = self._get_dashboard_tickets(email)
        if not all_tickets:
            # Nothing left under this email (e.g. session survived a data
            # change) — there is nothing to show, so start over.
            request.session.pop(DASHBOARD_SESSION_KEY, None)
            return request.redirect('/helpdesk/dashboard')

        for ticket in all_tickets:
            self._mark_ticket_verified(ticket.ticket_number)

        stage_filter = kwargs.get('filter') or 'all'
        if stage_filter not in self.DASHBOARD_STAGE_FILTERS:
            stage_filter = 'all'
        date_from = (kwargs.get('date_from') or '').strip()
        date_to = (kwargs.get('date_to') or '').strip()

        extra_domain = list(self.DASHBOARD_STAGE_FILTERS.get(stage_filter, []))
        extra_domain += self._dashboard_date_domain(date_from, date_to)
        tickets = self._get_dashboard_tickets(email, extra_domain) if extra_domain else all_tickets

        response = request.render(
            'client_helpdesk_portal.helpdesk_dashboard_view',
            {
                'email': email,
                'tickets': tickets,
                'total_count': len(all_tickets),
                'open_count': len(all_tickets.filtered(lambda t: not t.is_closed)),
                'resolved_count': len(all_tickets.filtered(lambda t: t.stage_id.name == 'Resolved')),
                'closed_count': len(all_tickets.filtered(lambda t: t.stage_id.name == 'Closed')),
                'stage_badge_map': STAGE_BADGE_CLASS,
                'current_filter': stage_filter,
                'date_from': date_from,
                'date_to': date_to,
                'stat_url_all': self._build_dashboard_url('all', date_from, date_to),
                'stat_url_open': self._build_dashboard_url('open', date_from, date_to),
                'stat_url_resolved': self._build_dashboard_url('resolved', date_from, date_to),
                'stat_url_closed': self._build_dashboard_url('closed', date_from, date_to),
                'clear_filters_url': '/helpdesk/dashboard/view',
            },
        )
        # Ticket list must always reflect current status, never a stale
        # cached copy — same no-cache policy as the single-ticket Track page.
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        return response

    @http.route('/helpdesk/dashboard/logout', type='http', auth='public', website=True)
    def helpdesk_dashboard_logout(self, **kwargs):
        request.session.pop(DASHBOARD_SESSION_KEY, None)
        return request.redirect('/helpdesk/dashboard')
