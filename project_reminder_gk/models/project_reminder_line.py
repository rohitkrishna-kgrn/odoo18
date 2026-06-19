import calendar
import logging
from datetime import date, datetime, timedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

_STATE_PRIORITY = {
    'upcoming': 1,
    'notification_sent': 2,
    'scheduled': 3,
    'completed': 4,
    'draft': 5,
    'cancelled': 6,
}


class ProjectReminderLine(models.Model):
    _name = 'project.reminder.line'
    _description = 'Project Reminder Line'
    _order = 'state_sequence asc, reminder_date asc, id asc'

    schedule_id = fields.Many2one(
        'project.reminder.schedule', string='Reminder Schedule',
        required=True, ondelete='cascade', index=True,
    )
    project_id = fields.Many2one(
        'project.project', string='Project',
        related='schedule_id.project_id', store=True, readonly=True, index=True,
    )
    project_manager_id = fields.Many2one(
        'res.users', string='Project Manager',
        related='schedule_id.project_manager_id', store=True, readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer',
        related='schedule_id.customer_id', store=True, readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order',
        related='schedule_id.sale_order_id', store=True, readonly=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sale Order Line',
        related='schedule_id.sale_order_line_id', store=True, readonly=True,
    )
    reminder_type = fields.Selection(
        related='schedule_id.reminder_type', string='Reminder Type',
        store=True, readonly=True,
    )
    period_label = fields.Char(
        string='Period',
        compute='_compute_period_label',
        store=True,
    )
    reminder_date = fields.Date(string='Reminder Date', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('upcoming', 'Upcoming'),
        ('notification_sent', 'Notification Sent'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', index=True)
    state_sequence = fields.Integer(
        compute='_compute_state_sequence', store=True, string='State Order',
    )
    color = fields.Integer(compute='_compute_color', store=True)

    # ── Notification tracking fields ─────────────────────────────────────────
    upcoming_mail_sent = fields.Boolean(
        string='Upcoming Mail Sent',
        default=False,
        help='Set to True after the upcoming reminder email (2 days before) is sent.',
    )
    due_today_mail_sent = fields.Boolean(
        string='Due Today Mail Sent',
        default=False,
        help='Set to True after the due-today reminder email is sent.',
    )
    notification_date = fields.Date(
        string='Email Notification Date',
        compute='_compute_notification_date',
        store=True,
        help='Date on which the upcoming reminder email will be dispatched (reminder_date − 2 days).',
    )
    remarks = fields.Text(related='schedule_id.remarks', string='Remarks', readonly=True)

    # ── Period helpers ────────────────────────────────────────────────────────

    @api.depends('reminder_date', 'reminder_type')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = self._derive_period_label(
                rec.reminder_date, rec.reminder_type
            ) or False

    @api.depends('reminder_date')
    def _compute_notification_date(self):
        for rec in self:
            rec.notification_date = (
                rec.reminder_date - timedelta(days=2) if rec.reminder_date else False
            )

    @api.model
    def _derive_period_label(self, reminder_date, reminder_type):
        """Return the human-readable period label for a given date and reminder type."""
        if not reminder_date or not reminder_type:
            return False
        month = reminder_date.month
        year = reminder_date.year
        if reminder_type == 'yearly':
            return str(year)
        if reminder_type == 'half_yearly':
            return f"H1 {year}" if month <= 6 else f"H2 {year}"
        if reminder_type == 'quarterly':
            q = (month - 1) // 3 + 1
            return f"Q{q} {year}"
        if reminder_type == 'monthly':
            return reminder_date.strftime('%B %Y')
        return False

    @api.model
    def _get_period_date_range(self, period_label, reminder_type):
        """Return (date_start, date_end) for a given period_label and reminder_type."""
        if not reminder_type or not period_label:
            return None, None
        try:
            if reminder_type == 'yearly':
                year = int(period_label.split()[0])
                return date(year, 1, 1), date(year, 12, 31)
            elif reminder_type == 'half_yearly':
                half, year = period_label.split()
                year = int(year)
                if half == 'H1':
                    return date(year, 1, 1), date(year, 6, 30)
                else:
                    return date(year, 7, 1), date(year, 12, 31)
            elif reminder_type == 'quarterly':
                q_str, year = period_label.split()
                q = int(q_str[1])
                year = int(year)
                month_start = (q - 1) * 3 + 1
                month_end = q * 3
                last_day = calendar.monthrange(year, month_end)[1]
                return date(year, month_start, 1), date(year, month_end, last_day)
            elif reminder_type == 'monthly':
                dt = datetime.strptime(period_label.strip(), '%B %Y')
                last_day = calendar.monthrange(dt.year, dt.month)[1]
                return date(dt.year, dt.month, 1), date(dt.year, dt.month, last_day)
        except (ValueError, IndexError, AttributeError):
            pass
        return None, None

    # ── State helpers ─────────────────────────────────────────────────────────

    @api.depends('state')
    def _compute_state_sequence(self):
        for rec in self:
            rec.state_sequence = _STATE_PRIORITY.get(rec.state, 9)

    _STATE_COLOR = {
        'upcoming': 2,            # orange — needs attention
        'notification_sent': 3,   # yellow-green — email sent, awaiting date
        'scheduled': 7,           # blue — future / planned
        'completed': 10,          # green — done
        'draft': 0,               # grey — inactive
        'cancelled': 1,           # red — cancelled
    }

    @api.depends('state')
    def _compute_color(self):
        for rec in self:
            rec.color = self._STATE_COLOR.get(rec.state, 0)

    def _set_state_from_date(self):
        """Auto-set line state based on reminder_date relative to today.

        notification_sent, completed, and cancelled are terminal — never
        overridden by date recalculation.
        """
        today = fields.Date.today()
        upcoming_threshold = today + timedelta(days=2)
        to_update = {}
        for rec in self:
            if not rec.reminder_date:
                continue
            # Terminal states: do not override with date logic
            if rec.state in ('notification_sent', 'completed', 'cancelled'):
                continue
            if rec.reminder_date < today:
                new_state = 'completed'
            elif rec.reminder_date <= upcoming_threshold:
                new_state = 'upcoming'
            else:
                new_state = 'scheduled'
            if rec.state != new_state:
                to_update.setdefault(new_state, self.browse())
                to_update[new_state] |= rec
        for new_state, records in to_update.items():
            records.with_context(skip_state_recompute=True).write({'state': new_state})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state != 'cancelled')._set_state_from_date()
        return records

    def write(self, vals):
        result = super().write(vals)
        if 'reminder_date' in vals and not self.env.context.get('skip_state_recompute'):
            self.filtered(
                lambda r: r.state not in ('notification_sent', 'cancelled')
            )._set_state_from_date()
        return result

    def action_complete(self):
        for rec in self:
            if rec.state in ('upcoming', 'notification_sent'):
                rec.state = 'completed'
                rec.schedule_id._refresh_state_from_lines()

    def action_cancel_reminder(self):
        for rec in self:
            rec.with_context(skip_state_recompute=True).write({'state': 'cancelled'})
            rec.schedule_id._refresh_state_from_lines()
