import html as _html
from odoo import api, fields, models

ACTION_CONFIG = {
    'resolve': {
        'stage': 'Resolved',
        'notes_heading': 'Resolved Remarks',
        'reason_label': 'Resolved Remarks',
        'placeholder': 'Please add your remarks for resolving this ticket…',
    },
    'close': {
        'stage': 'Closed',
        'notes_heading': 'Closed Reason',
        'reason_label': 'Close Reason',
        'placeholder': 'Please describe why this ticket is being closed…',
    },
}


class HelpdeskCloseWizard(models.TransientModel):
    _name = 'client.helpdesk.close.wizard'
    _description = 'Ticket Action – Remarks / Reason'

    action_type = fields.Selection([
        ('resolve', 'Resolve'),
        ('close', 'Close'),
    ], string='Action', required=True, default='close', readonly=True)

    ticket_id = fields.Many2one(
        'client.helpdesk.ticket', string='Ticket', required=True, readonly=True,
    )
    ticket_number = fields.Char(
        string='Ticket #', compute='_compute_ticket_details', store=False,
    )
    subject = fields.Char(
        string='Subject', compute='_compute_ticket_details', store=False,
    )
    reason = fields.Text(
        'Remarks', required=True,
    )

    @api.depends('ticket_id')
    def _compute_ticket_details(self):
        for rec in self:
            rec.ticket_number = rec.ticket_id.ticket_number or ''
            rec.subject = rec.ticket_id.subject or ''

    def action_confirm(self):
        ticket = self.ticket_id
        cfg = ACTION_CONFIG.get(self.action_type, ACTION_CONFIG['close'])
        reason_safe = _html.escape(self.reason).replace('\n', '<br/>')
        notes_block = (
            f'<p><strong>{cfg["notes_heading"]}</strong></p>'
            f'<p>{reason_safe}</p>'
        )
        existing = ticket.internal_notes or ''
        separator = '<hr/>' if existing.strip() else ''
        ticket.write({'internal_notes': existing + separator + notes_block})
        # Pass reason via context so _notify_stage_change includes it in emails.
        ticket.with_context(
            helpdesk_close_reason=self.reason,
            helpdesk_close_action_type=self.action_type,
        )._move_to_stage(cfg['stage'])
        return {'type': 'ir.actions.act_window_close'}
