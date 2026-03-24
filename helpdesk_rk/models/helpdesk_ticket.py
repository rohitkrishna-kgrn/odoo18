import re
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class HelpdeskTicket(models.Model):
    _name = 'helpdesk_rk.ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Helpdesk Ticket'
    _order = 'id desc'

    STAGE_SELECTION = [
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('rejected', 'Rejected'),
    ]

    name = fields.Char('Subject', required=True, tracking=True)
    description = fields.Text('Description', tracking=True)
    ticket_number = fields.Char('Ticket Number', readonly=True, copy=False, index=True)
    stage_id = fields.Selection(STAGE_SELECTION, string='Stage', default='new', tracking=True, required=True, index=True)
    user_id = fields.Many2one('res.users', 'Created By', default=lambda self: self.env.user)
    email_to = fields.Char('Assigned Team Email', readonly=True)
    mail_message_id = fields.Many2one('mail.message', string="Original Email")
    attachment = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="Attachment Filename")
    active = fields.Boolean(default=True)

    def _get_support_team_emails(self):
        param = self.env['ir.config_parameter'].sudo()
        saved_ids = param.get_param('helpdesk_rk.support_team_ids', '')
        if not saved_ids:
            return False
        users = self.env['res.users'].browse(map(int, saved_ids.split(',')))
        return ','.join(users.mapped('email')) or False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['email_to'] = self._get_support_team_emails() or ''
            vals['ticket_number'] = self.env['ir.sequence'].next_by_code('helpdesk_rk.ticket') or 'TCKT00001'
        records = super().create(vals_list)
        for rec in records:
            rec._send_stage_email('New', to_support=True)
            rec._send_stage_email('New', to_support=False)
        return records

    def write(self, vals):
        for rec in self:
            if rec.stage_id in ['done', 'rejected']:
                raise ValidationError("You cannot modify a ticket that is Done or Rejected.")
        return super().write(vals)

    def _send_stage_email(self, stage_name, to_support=False):
        company = self.env.user.company_id
        logo_url = "https://kompanyservices.com/wp-content/uploads/logo-kgrn.png"
        support_email = self._get_support_team_emails() or 'support@yourcompany.com'
        company_name = company.name or "Your Company"
        year = fields.Date.today().year

        if to_support:
            email_to = support_email
            subject = f"[Helpdesk] New Ticket #{self.ticket_number}: {self.name}"
            email_heading = "New Helpdesk Ticket Submitted"
            email_message = "A new helpdesk ticket has been submitted by a user. Please review and take action."
            ticket_url = '#'
        else:
            if not self.user_id.email:
                _logger.warning(f"User email missing for ticket {self.ticket_number}")
                return
            email_to = self.user_id.email
            subject = f"Thank You - Helpdesk Ticket #{self.ticket_number} Received"
            email_heading = "Thank You for Contacting Support"
            email_message = "Your support request has been received. Our team will review it and get back to you shortly."

        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Ticket Email</title></head>
<body style="margin:0;padding:0;background:#f4f6f9;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f9;font-family:Arial,sans-serif;">
<tr><td align="center">
  <table width="700" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e1e4e8;border-radius:8px;margin:20px 0;">
    <tr><td style="background:#003366;padding:20px;text-align:center;">
      <img src="{logo_url}" alt="Logo" width="100" height="100" style="display:block;margin:0 auto;border:0;" />
    </td></tr>
    <tr><td style="padding:40px 30px;">
      <h1 style="color:#003366;font-size:20px;margin:0 0 20px;">{email_heading}</h1>
      <table width="100%" cellpadding="0" cellspacing="0"><tr><td>
        <table width="100%" cellpadding="0" cellspacing="0" style="padding:0 0 20px 0;">
          <tr><td style="font-size:15px;color:#333;line-height:1.6;">{email_message}</td></tr>
        </table>
      </td></tr></table>

      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f6ff;border-left:5px solid #004080;">
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Ticket #:</strong>{self.ticket_number}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Subject:</strong>{self.name}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Status:</strong>{stage_name.replace('_',' ').title()}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Description:</strong>{self.description or '-'}</td></tr>
        <tr><td style="padding:10px 15px;font-size:14px;"><strong style="display:inline-block;width:130px;color:#004080;">Submitted By:</strong>{self.user_id.name}</td></tr>
      </table>

    </td></tr>
    <tr><td style="background:#fafbfc;text-align:center;font-size:13px;color:#888;padding:20px;">
      &copy; {year} {company_name}. For assistance, <a href="mailto:{support_email}" style="color:#888;">{support_email}</a>
    </td></tr>
  </table>
</td></tr></table>
</body>
</html>
"""
        mail_values = {
            'subject': subject,
            'body_html': body_html,
            'email_to': email_to,
            'author_id': self.env.user.partner_id.id,
            'model': self._name,
            'res_id': self.id,
        }
        try:
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.sudo().send()
            _logger.info(f"Email sent for ticket #{self.ticket_number} to {email_to}")
        except Exception as e:
            _logger.error(f"Failed to send email for ticket #{self.ticket_number}: {e}")

    def _check_user_in_support_team(self):
        config = self.env['helpdesk_rk.config'].sudo().search([], limit=1)
        return self.env.user.has_group('base.group_system') or (config and self.env.user in config.support_team_ids)

    def action_set_in_progress(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        self.stage_id = 'in_progress'
        self._send_stage_email('In Progress', to_support=False)

    def action_set_done(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        self.stage_id = 'done'
        self._send_stage_email('Done', to_support=False)

    def action_set_rejected(self):
        if not self._check_user_in_support_team(): raise UserError("Not authorized.")
        self.stage_id = 'rejected'
        self._send_stage_email('Rejected', to_support=False)
