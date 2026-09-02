"""Drop follow-ups the 2.11 backfill took from OdooBot.

OdooBot posts a handful of genuine Log notes on customer invoices -- "The
invoice already contains lines, it was not updated from the attachment" is the
common one -- and the first backfill read them as chases. A follow-up is a
person chasing a client, so the system talking to itself must not count, or
the AR report credits AR with work nobody did and the No Follow-Up Logged flag
clears on an invoice nobody has touched.

_prepare_from_message now refuses them at source; this removes the ones already
written. Only rows that came from a chatter message are touched, so anything
entered by hand through the old tab is left alone.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    odoobot = env.ref('base.partner_root', raise_if_not_found=False)
    if not odoobot:
        return

    logs = env['account.invoice.followup.log'].sudo().search([
        ('message_id', '!=', False),
        ('message_id.author_id', '=', odoobot.id),
    ])
    moves = logs.move_id
    _logger.info(
        "Follow-up log: removing %s OdooBot-authored follow-up(s) on %s "
        "invoice(s).", len(logs), len(moves))
    logs.unlink()

    # The flag and the last-follow-up fields were computed with those rows in
    # place; an invoice whose only "follow-up" was OdooBot must go back to
    # being flagged as never chased.
    moves = moves.exists()
    if moves:
        moves.modified(['followup_log_ids'])
        moves._compute_last_followup()
        moves._compute_followup_log_status()
        moves._compute_ar_no_followup_flag()
        moves._compute_ar_close_lock()
        moves.flush_recordset()

    _logger.info("Follow-up log: OdooBot cleanup complete.")
