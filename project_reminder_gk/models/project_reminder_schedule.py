import logging
from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_STATE_PRIORITY = {
    'upcoming': 1,
    'notification_sent': 2,
    'scheduled': 3,
    'completed': 4,
    'draft': 5,
    'cancelled': 6,
}


class ProjectReminderSchedule(models.Model):
    _name = 'project.reminder.schedule'
    _description = 'Project Reminder Schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state_sequence asc, create_date desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    project_id = fields.Many2one(
        'project.project', string='Project',
        required=True, ondelete='cascade', index=True,
    )
    project_sale_order_id = fields.Many2one(
        'sale.order', string='Project Sale Order',
        related='project_id.sale_order_id', store=False, readonly=True,
    )
    sale_order_id = fields.Many2one(
        'sale.order', string='Sale Order',
        compute='_compute_sale_order_id', store=True, readonly=True,
    )
    sale_order_line_id = fields.Many2one(
        'sale.order.line', string='Sale Order Line', required=True,
    )
    project_manager_id = fields.Many2one(
        'res.users', string='Project Manager',
        related='project_id.user_id', store=True, readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer',
        related='project_id.partner_id', store=True, readonly=True,
    )
    reminder_type = fields.Selection([
        ('yearly', 'Yearly Reminder'),
        ('half_yearly', 'Half-Yearly Reminder'),
        ('quarterly', 'Quarterly Reminder'),
        ('monthly', 'Monthly Reminder'),
    ], string='Reminder Type', required=True, tracking=True)
    yearly_frequency = fields.Selection([
        ('1', 'One Reminder Per Year'),
        ('2', 'Two Reminders Per Year'),
        ('3', 'Three Reminders Per Year'),
    ], string='Yearly Frequency', default='1')
    engagement_start = fields.Date(
        string='Engagement Start',
        related='sale_order_line_id.engagement_start', store=True, readonly=True,
    )
    engagement_end = fields.Date(
        string='Engagement End',
        related='sale_order_line_id.engagement_end', store=True, readonly=True,
    )
    remarks = fields.Text(string='Remarks')
    line_ids = fields.One2many('project.reminder.line', 'schedule_id', string='Reminder Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('upcoming', 'Upcoming'),
        ('notification_sent', 'Notification Sent'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    state_sequence = fields.Integer(
        compute='_compute_state_sequence', store=True, string='State Order',
    )
    line_count = fields.Integer(compute='_compute_line_count', string='Lines')

    @api.depends('sale_order_line_id')
    def _compute_sale_order_id(self):
        for rec in self:
            rec.sale_order_id = rec.sale_order_line_id.order_id if rec.sale_order_line_id else False

    @api.depends('state')
    def _compute_state_sequence(self):
        for rec in self:
            rec.state_sequence = _STATE_PRIORITY.get(rec.state, 9)

    @api.depends('project_id', 'reminder_type')
    def _compute_name(self):
        type_labels = dict(self._fields['reminder_type'].selection)
        for rec in self:
            type_label = type_labels.get(rec.reminder_type, '')
            rec.name = f"{rec.project_id.name or ''} – {type_label}" if rec.project_id else type_label

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_schedule(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Add reminder dates before scheduling."))
            rec.line_ids.filtered(lambda l: l.state == 'draft').write({'state': 'scheduled'})
            rec.state = 'scheduled'
            rec.message_post(body=_("Reminder schedule activated."))

    def action_cancel(self):
        for rec in self:
            rec.line_ids.write({'state': 'cancelled'})
            rec.state = 'cancelled'
            rec.message_post(body=_("Reminder cancelled."))

    def action_reset_draft(self):
        for rec in self:
            rec.line_ids.write({'state': 'draft'})
            rec.state = 'draft'
            rec.message_post(body=_("Reset to draft."))

    def _refresh_state_from_lines(self):
        """Re-evaluate schedule state based on the current state of its lines."""
        for schedule in self:
            active_lines = schedule.line_ids.filtered(lambda l: l.state != 'cancelled')
            if not active_lines:
                continue
            states = set(active_lines.mapped('state'))
            if states <= {'completed'}:
                if schedule.state != 'completed':
                    schedule.state = 'completed'
            elif 'upcoming' in states:
                if schedule.state != 'upcoming':
                    schedule.state = 'upcoming'
            elif 'notification_sent' in states:
                if schedule.state != 'notification_sent':
                    schedule.state = 'notification_sent'
            elif 'scheduled' in states:
                if schedule.state != 'scheduled':
                    schedule.state = 'scheduled'

    # ── Cron: Status Update ──────────────────────────────────────────────────

    @api.model
    def _cron_update_statuses(self):
        """Daily: transition line states based on reminder_date vs. today."""
        today = fields.Date.today()
        upcoming_threshold = today + timedelta(days=2)

        # Transition scheduled/upcoming/notification_sent lines by date
        lines = self.env['project.reminder.line'].search([
            ('state', 'in', ['scheduled', 'upcoming', 'notification_sent']),
        ])
        for line in lines:
            if not line.reminder_date:
                continue
            if line.reminder_date < today:
                # Reminder date has passed — mark completed
                line.with_context(skip_state_recompute=True).write({'state': 'completed'})
            elif line.reminder_date <= upcoming_threshold and line.state == 'scheduled':
                # Within 2-day window — elevate to upcoming
                line.with_context(skip_state_recompute=True).write({'state': 'upcoming'})

        # Reflect line state changes back to parent schedules
        for schedule in self.search([('state', 'in', ['draft', 'scheduled', 'upcoming', 'notification_sent'])]):
            active_lines = schedule.line_ids.filtered(lambda l: l.state != 'cancelled')
            if not active_lines:
                continue
            states = set(active_lines.mapped('state'))
            if states <= {'completed'}:
                schedule.state = 'completed'
            elif 'upcoming' in states:
                schedule.state = 'upcoming'
            elif 'notification_sent' in states:
                schedule.state = 'notification_sent'

    # ── Cron: Upcoming Reminder Notification ─────────────────────────────────

    @api.model
    def _cron_upcoming_reminder_notification(self):
        """Daily: send 'Upcoming Reminder' email exactly 2 days before reminder_date.

        Idempotent — upcoming_mail_sent flag prevents duplicate sends on the
        same day or if the cron fires more than once.
        """
        target_date = fields.Date.today() + timedelta(days=2)
        lines = self.env['project.reminder.line'].search([
            ('reminder_date', '=', target_date),
            ('state', 'in', ['scheduled', 'upcoming']),
            ('upcoming_mail_sent', '=', False),
        ])
        if not lines:
            _logger.info('Upcoming Reminder Notification: no lines due on %s', target_date)
            return

        template = self.env.ref(
            'project_reminder_gk.email_template_individual_reminder',
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning('Upcoming Reminder Notification: email template not found — skipping.')
            return

        sent_count = 0
        for line in lines:
            if not line.project_manager_id or not line.project_manager_id.email:
                _logger.warning(
                    'Upcoming Reminder: line %s has no project manager email — skipped.', line.id
                )
                continue
            try:
                rendered = template._generate_template(
                    [line.id], ['subject', 'body_html', 'email_from', 'email_to']
                )
                vals = rendered[line.id]
                mail = self.env['mail.mail'].sudo().create({
                    'subject': vals.get('subject', ''),
                    'body_html': vals.get('body_html', ''),
                    'email_from': vals.get('email_from', ''),
                    'email_to': vals.get('email_to', ''),
                    'auto_delete': False,
                })
                mail.sudo().send(raise_exception=True)
                line.upcoming_mail_sent = True
                sent_count += 1
                # Log in parent schedule chatter
                line.schedule_id.message_post(
                    body=_(
                        "Upcoming reminder email sent to <b>%s</b> for <b>%s</b> "
                        "(due on %s)."
                    ) % (
                        line.project_manager_id.name,
                        line.project_id.name,
                        line.reminder_date.strftime('%d-%b-%Y'),
                    )
                )
            except Exception as exc:
                _logger.error(
                    'Upcoming Reminder: failed to send email for line %s — %s', line.id, exc
                )

        _logger.info(
            'Upcoming Reminder Notification: %d/%d email(s) sent for date %s.',
            sent_count, len(lines), target_date,
        )

    # ── Cron: Due Today Reminder Notification ────────────────────────────────

    @api.model
    def _cron_due_today_reminder_notification(self):
        """Daily: send 'Due Today' email on the actual reminder_date.

        After a successful send the line status is promoted to
        'notification_sent' and due_today_mail_sent is set to True.
        Idempotent — due_today_mail_sent flag prevents duplicate sends.
        """
        today = fields.Date.today()
        lines = self.env['project.reminder.line'].search([
            ('reminder_date', '=', today),
            ('state', 'in', ['scheduled', 'upcoming']),
            ('due_today_mail_sent', '=', False),
        ])
        if not lines:
            _logger.info('Due Today Reminder Notification: no lines due on %s', today)
            return

        template = self.env.ref(
            'project_reminder_gk.email_template_due_reminder',
            raise_if_not_found=False,
        )
        if not template:
            _logger.warning('Due Today Reminder Notification: email template not found — skipping.')
            return

        sent_count = 0
        for line in lines:
            if not line.project_manager_id or not line.project_manager_id.email:
                _logger.warning(
                    'Due Today Reminder: line %s has no project manager email — skipped.', line.id
                )
                continue
            try:
                rendered = template._generate_template(
                    [line.id], ['subject', 'body_html', 'email_from', 'email_to']
                )
                vals = rendered[line.id]
                mail = self.env['mail.mail'].sudo().create({
                    'subject': vals.get('subject', ''),
                    'body_html': vals.get('body_html', ''),
                    'email_from': vals.get('email_from', ''),
                    'email_to': vals.get('email_to', ''),
                    'auto_delete': False,
                })
                mail.sudo().send(raise_exception=True)
                # Mark sent and elevate line status to notification_sent
                line.write({
                    'due_today_mail_sent': True,
                    'state': 'notification_sent',
                })
                sent_count += 1
                # Log in parent schedule chatter
                line.schedule_id.message_post(
                    body=_(
                        "Due Today reminder email sent to <b>%s</b> for <b>%s</b> "
                        "(reminder date: %s). Status updated to <b>Notification Sent</b>."
                    ) % (
                        line.project_manager_id.name,
                        line.project_id.name,
                        line.reminder_date.strftime('%d-%b-%Y'),
                    )
                )
                # Reflect line state change on parent schedule
                line.schedule_id._refresh_state_from_lines()
            except Exception as exc:
                _logger.error(
                    'Due Today Reminder: failed to send email for line %s — %s', line.id, exc
                )

        _logger.info(
            'Due Today Reminder Notification: %d/%d email(s) sent for date %s.',
            sent_count, len(lines), today,
        )

    # ── Cron: Monthly PM Summary ─────────────────────────────────────────────

    @api.model
    def _cron_send_monthly_pm_summary(self):
        """Monthly consolidated email per Project Manager (1st of month)."""
        today = fields.Date.today()
        month_start = today.replace(day=1)
        if today.month == 12:
            month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

        lines = self.env['project.reminder.line'].search([
            ('reminder_date', '>=', month_start),
            ('reminder_date', '<=', month_end),
            ('state', 'in', ['scheduled', 'upcoming']),
        ], order='reminder_date asc')

        pm_map = {}
        for line in lines:
            pm = line.project_manager_id
            if not pm or not pm.email:
                continue
            pm_map.setdefault(pm.id, {'pm': pm, 'lines': self.env['project.reminder.line']})
            pm_map[pm.id]['lines'] |= line

        type_labels = {
            'yearly': 'Yearly',
            'half_yearly': 'Half-Yearly',
            'quarterly': 'Quarterly',
            'monthly': 'Monthly',
        }
        month_label = today.strftime('%B %Y')

        pm_mails = self.env['mail.mail'].sudo()
        for data in pm_map.values():
            pm = data['pm']
            rows = ''.join(
                f"""<tr>
                  <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.project_id.name or '&mdash;'}</td>
                  <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.customer_id.name or '&mdash;'}</td>
                  <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.sale_order_id.name or '&mdash;'}</td>
                  <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{type_labels.get(ln.reminder_type, ln.reminder_type)}</td>
                  <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.reminder_date.strftime('%d-%b-%Y') if ln.reminder_date else '&mdash;'}</td>
                </tr>"""
                for ln in data['lines'].sorted('reminder_date')
            )
            body = f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7;font-family:Arial,Helvetica,sans-serif;line-height:1.6;">
  <tr>
    <td align="center" valign="top" style="padding:24px 12px;">
      <table role="presentation" width="620" cellpadding="0" cellspacing="0" border="0" align="center" style="width:620px;max-width:620px;background-color:#ffffff;border:1px solid #dde6f0;">
        <tr>
          <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:18px 28px;">
            <h1 style="color:#ffffff;font-size:18px;font-weight:700;margin:0 0 3px 0;letter-spacing:0.2px;font-family:Arial,Helvetica,sans-serif;mso-line-height-rule:exactly;">Monthly Project Reminders &#8211; {month_label}</h1>
            <p style="color:#a8c4e8;font-size:12px;margin:0;font-family:Arial,Helvetica,sans-serif;mso-line-height-rule:exactly;">KGRN Project Management</p>
          </td>
        </tr>
        <tr>
          <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:22px 28px;">
            <p style="margin:0 0 4px 0;color:#222222;font-size:14px;font-family:Arial,Helvetica,sans-serif;">Dear <strong>{pm.name}</strong>,</p>
            <p style="margin:0 0 18px 0;color:#555555;font-size:13px;font-family:Arial,Helvetica,sans-serif;">Your project reminders for <strong>{month_label}</strong> are listed below. Please ensure all obligations are addressed before their respective reminder dates.</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;border:1px solid #c5d7f0;margin:0 0 18px 0;">
              <tr>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Project</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Customer</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">SO Number</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Type</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Date</td>
              </tr>
              {rows}
            </table>
            <p style="margin:0;color:#555555;font-size:13px;font-family:Arial,Helvetica,sans-serif;">Please log in to Odoo to view full details and take necessary action.</p>
          </td>
        </tr>
        <tr>
          <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:12px 28px;text-align:center;">
            <p style="color:#a8c4e8;font-size:12px;margin:0;line-height:1.5;font-family:Arial,Helvetica,sans-serif;">This is an automated notification from the KGRN Project Management system.</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""
            pm_mails |= self.env['mail.mail'].sudo().create({
                'subject': f'Monthly Project Reminders – {month_label}',
                'body_html': body,
                'email_to': pm.email,
                'auto_delete': False,
            })
        if pm_mails:
            pm_mails.send(raise_exception=False)

    # ── Cron: Monthly Approver Summary ──────────────────────────────────────

    @api.model
    def _cron_send_monthly_approver_summary(self):
        """Monthly management summary to company approver (1st of month)."""
        company = self.env.company
        approver = company.approver_user_id
        if not approver or not approver.email:
            return

        today = fields.Date.today()
        month_start = today.replace(day=1)
        if today.month == 12:
            month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

        lines = self.env['project.reminder.line'].search([
            ('reminder_date', '>=', month_start),
            ('reminder_date', '<=', month_end),
            ('state', 'in', ['scheduled', 'upcoming']),
        ], order='project_manager_id asc, reminder_date asc')
        if not lines:
            return

        type_labels = {
            'yearly': 'Yearly',
            'half_yearly': 'Half-Yearly',
            'quarterly': 'Quarterly',
            'monthly': 'Monthly',
        }
        month_label = today.strftime('%B %Y')

        rows = ''.join(
            f"""<tr>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.project_manager_id.name or '&mdash;'}</td>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.project_id.name or '&mdash;'}</td>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.customer_id.name or '&mdash;'}</td>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.sale_order_id.name or '&mdash;'}</td>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;border-right:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{type_labels.get(ln.reminder_type, ln.reminder_type)}</td>
              <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:8px 14px;border-bottom:1px solid #dde6f0;color:#333333;font-size:12px;font-family:Arial,Helvetica,sans-serif;">{ln.reminder_date.strftime('%d-%b-%Y') if ln.reminder_date else '&mdash;'}</td>
            </tr>"""
            for ln in lines
        )
        body = f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eef2f7;font-family:Arial,Helvetica,sans-serif;line-height:1.6;">
  <tr>
    <td align="center" valign="top" style="padding:24px 12px;">
      <table role="presentation" width="660" cellpadding="0" cellspacing="0" border="0" align="center" style="width:660px;max-width:660px;background-color:#ffffff;border:1px solid #dde6f0;">
        <tr>
          <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:18px 28px;">
            <h1 style="color:#ffffff;font-size:18px;font-weight:700;margin:0 0 3px 0;letter-spacing:0.2px;font-family:Arial,Helvetica,sans-serif;mso-line-height-rule:exactly;">Management Summary &#8211; Project Reminders {month_label}</h1>
            <p style="color:#a8c4e8;font-size:12px;margin:0;font-family:Arial,Helvetica,sans-serif;mso-line-height-rule:exactly;">KGRN Project Management</p>
          </td>
        </tr>
        <tr>
          <td valign="top" bgcolor="#ffffff" style="background-color:#ffffff;padding:22px 28px;">
            <p style="margin:0 0 4px 0;color:#222222;font-size:14px;font-family:Arial,Helvetica,sans-serif;">Dear <strong>{approver.name}</strong>,</p>
            <p style="margin:0 0 18px 0;color:#555555;font-size:13px;font-family:Arial,Helvetica,sans-serif;">Below is the management summary of all project reminders for <strong>{month_label}</strong>.</p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;border:1px solid #c5d7f0;margin:0 0 18px 0;">
              <tr>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Project Manager</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Project</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Customer</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">SO Number</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;border-right:1px solid #2563ab;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Type</td>
                <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:9px 14px;color:#ffffff;font-weight:700;font-size:12px;font-family:Arial,Helvetica,sans-serif;">Date</td>
              </tr>
              {rows}
            </table>
            <p style="margin:0;color:#555555;font-size:13px;font-family:Arial,Helvetica,sans-serif;">Please log in to Odoo to view full details and follow up as needed.</p>
          </td>
        </tr>
        <tr>
          <td valign="top" bgcolor="#1a3c6e" style="background-color:#1a3c6e;padding:12px 28px;text-align:center;">
            <p style="color:#a8c4e8;font-size:12px;margin:0;line-height:1.5;font-family:Arial,Helvetica,sans-serif;">This is an automated notification from the KGRN Project Management system.</p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>"""
        mail = self.env['mail.mail'].sudo().create({
            'subject': f'Management Summary – Project Reminders {month_label}',
            'body_html': body,
            'email_to': approver.email,
            'auto_delete': False,
        })
        mail.send(raise_exception=False)
