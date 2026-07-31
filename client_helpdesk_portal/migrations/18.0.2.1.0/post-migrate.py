"""Backfill client.helpdesk.reason.line from the old free-text/HTML storage.

Read-only extraction: resume_reason and internal_notes are never modified,
only parsed. Each of the three passes below is independent and best-effort
per ticket — a parsing failure on one ticket must not abort the others.
"""
import html
import logging
import re
from datetime import datetime, timedelta

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

GST_OFFSET = timedelta(hours=4)

RESUME_LINE_RE = re.compile(
    r'^(?P<when>\d{1,2} \w{3} \d{4} at \d{2}:\d{2}) GST: (?P<reason>.*)$'
)
NOTES_BLOCK_RE = re.compile(
    r'<p><strong>(Resolved Remarks|Closed Reason)</strong></p>\s*<p>(.*?)</p>',
    re.DOTALL,
)
REOPEN_BODY_RE = re.compile(
    r'<p><strong>Reopened by Client</strong></p>\s*<p>(.*?)</p>', re.DOTALL,
)
BR_RE = re.compile(r'<br\s*/?>', re.IGNORECASE)

NOTES_HEADING_TO_ACTION = {
    'Resolved Remarks': 'resolve',
    'Closed Reason': 'close',
}
NOTES_HEADING_TO_STAGE = {
    'Resolved Remarks': 'Resolved',
    'Closed Reason': 'Closed',
}


def _html_block_to_text(raw):
    return html.unescape(BR_RE.sub('\n', raw)).strip()


def _migrate_resume_reason(cr, ReasonLine):
    cr.execute("""
        SELECT id, resume_reason FROM client_helpdesk_ticket
         WHERE resume_reason IS NOT NULL AND trim(resume_reason) != ''
    """)
    rows = cr.fetchall()
    unmatched = 0
    for ticket_id, resume_reason in rows:
        try:
            for line in resume_reason.split('\n'):
                line = line.strip()
                if not line:
                    continue
                match = RESUME_LINE_RE.match(line)
                if not match:
                    unmatched += 1
                    _logger.warning(
                        'client_helpdesk_reason_line migration: could not parse '
                        'resume_reason line on ticket id %s: %r', ticket_id, line,
                    )
                    continue
                when = datetime.strptime(match.group('when'), '%d %b %Y at %H:%M')
                ReasonLine.create({
                    'ticket_id': ticket_id,
                    'action_type': 'resume',
                    'date_time': when - GST_OFFSET,
                    'reason': match.group('reason'),
                })
        except Exception:
            _logger.exception(
                'client_helpdesk_reason_line migration: failed on resume_reason '
                'for ticket id %s', ticket_id,
            )
    if unmatched:
        _logger.warning(
            'client_helpdesk_reason_line migration: %d resume_reason line(s) '
            'could not be parsed and were skipped', unmatched,
        )


def _tracking_timestamps(cr, ticket_id, stage_name):
    """Chronological create_date of every mail.message where stage_id was
    tracked as changing to stage_name, for this ticket."""
    cr.execute("""
        SELECT mm.create_date
          FROM mail_tracking_value mtv
          JOIN mail_message mm ON mm.id = mtv.mail_message_id
          JOIN ir_model_fields imf ON imf.id = mtv.field_id
         WHERE mm.model = 'client.helpdesk.ticket'
           AND mm.res_id = %s
           AND imf.name = 'stage_id'
           AND mtv.new_value_char = %s
         ORDER BY mm.create_date ASC
    """, (ticket_id, stage_name))
    return [row[0] for row in cr.fetchall()]


def _migrate_internal_notes(cr, ReasonLine):
    cr.execute("""
        SELECT id, internal_notes, closed_date, write_date
          FROM client_helpdesk_ticket
         WHERE internal_notes IS NOT NULL AND trim(internal_notes) != ''
    """)
    rows = cr.fetchall()
    no_match_count = 0
    for ticket_id, internal_notes, closed_date, write_date in rows:
        try:
            blocks = NOTES_BLOCK_RE.findall(internal_notes)
            if not blocks:
                no_match_count += 1
                continue
            fallback_dt = closed_date or write_date
            # Track a separate chronological cursor per heading type, since a
            # ticket can be resolved/reopened/closed more than once and each
            # heading only correlates with tracking events of its own stage.
            timestamp_cursors = {}
            for heading, raw_reason in blocks:
                action_type = NOTES_HEADING_TO_ACTION[heading]
                stage_name = NOTES_HEADING_TO_STAGE[heading]
                if heading not in timestamp_cursors:
                    timestamp_cursors[heading] = _tracking_timestamps(
                        cr, ticket_id, stage_name,
                    )
                available = timestamp_cursors[heading]
                date_time = available.pop(0) if available else fallback_dt
                if date_time is None:
                    _logger.warning(
                        'client_helpdesk_reason_line migration: no timestamp '
                        'available for a %s block on ticket id %s, skipping',
                        heading, ticket_id,
                    )
                    continue
                ReasonLine.create({
                    'ticket_id': ticket_id,
                    'action_type': action_type,
                    'date_time': date_time,
                    'reason': _html_block_to_text(raw_reason),
                })
        except Exception:
            _logger.exception(
                'client_helpdesk_reason_line migration: failed on internal_notes '
                'for ticket id %s', ticket_id,
            )
    if no_match_count:
        _logger.warning(
            'client_helpdesk_reason_line migration: %d ticket(s) had non-empty '
            'internal_notes with no recognizable Resolved/Closed block '
            '(left untouched, likely hand-typed notes only)', no_match_count,
        )


def _migrate_reopen_chatter(cr, ReasonLine):
    cr.execute("""
        SELECT res_id, create_date, body FROM mail_message
         WHERE model = 'client.helpdesk.ticket'
           AND subject = 'Ticket Reopened by Client'
           AND res_id IS NOT NULL
    """)
    rows = cr.fetchall()
    for ticket_id, create_date, body in rows:
        try:
            match = REOPEN_BODY_RE.search(body or '')
            reason = (
                _html_block_to_text(match.group(1)) if match else ''
            ) or 'Reopened by client (reason not recorded).'
            ReasonLine.create({
                'ticket_id': ticket_id,
                'action_type': 'reopen',
                'date_time': create_date,
                'reason': reason,
            })
        except Exception:
            _logger.exception(
                'client_helpdesk_reason_line migration: failed on reopen '
                'chatter message for ticket id %s', ticket_id,
            )


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ReasonLine = env['client.helpdesk.reason.line']

    _migrate_resume_reason(cr, ReasonLine)
    _migrate_internal_notes(cr, ReasonLine)
    _migrate_reopen_chatter(cr, ReasonLine)
