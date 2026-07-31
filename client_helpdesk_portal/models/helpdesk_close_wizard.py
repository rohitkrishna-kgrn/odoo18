from odoo import api, fields, models

ACTION_CONFIG = {
    'resolve': {
        'stage': 'Resolved',
        'placeholder': 'Please add your remarks for resolving this ticket…',
    },
    'close': {
        'stage': 'Closed',
        'placeholder': 'Please describe why this ticket is being closed…',
    },
    'resume': {
        'stage': 'In Progress',
        'placeholder': 'Please describe why this ticket is being moved back to In Progress…',
    },
}


class HelpdeskCloseWizard(models.TransientModel):
    _name = 'client.helpdesk.close.wizard'
    _description = 'Ticket Action – Remarks / Reason'

    action_type = fields.Selection([
        ('resolve', 'Resolve'),
        ('close', 'Close'),
        ('resume', 'Resume'),
    ], string='Action', required=True, default='close', readonly=True)

    ticket_id = fields.Many2one(
        'client.helpdesk.ticket', string='Ticket', required=True, readonly=True,
    )
    ticket_number = fields.Char(
        string='Ticket Number', compute='_compute_ticket_details', store=False,
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

        # Every resolve/close/resume reason is recorded as its own row on
        # client.helpdesk.reason.line, rendered as a Date/Time/Reason table
        # on the ticket form instead of being folded into a text/HTML blob.
        self.env['client.helpdesk.reason.line'].create({
            'ticket_id': ticket.id,
            'action_type': self.action_type,
            'reason': self.reason,
        })

        if self.action_type == 'resume':
            ticket._move_to_stage(cfg['stage'])
            return {'type': 'ir.actions.act_window_close'}

        # Pass reason via context so _notify_stage_change includes it in emails.
        ticket.with_context(
            helpdesk_close_reason=self.reason,
            helpdesk_close_action_type=self.action_type,
        )._move_to_stage(cfg['stage'])
        return {'type': 'ir.actions.act_window_close'}
