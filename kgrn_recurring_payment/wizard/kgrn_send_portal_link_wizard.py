from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KgrnSendPortalLinkWizard(models.TransientModel):
    _name = 'kgrn.send.portal.link.wizard'
    _description = 'Send KGRN Recurring Payment Portal Link'

    contract_id = fields.Many2one(
        'kgrn.recurring.contract',
        string='Contract',
        required=True,
        readonly=True,
    )
    recipient_email = fields.Char(string='Recipient Email', required=True)
    subject = fields.Char(string='Subject', required=True)
    body_html = fields.Html(string='Message', sanitize=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        contract_id = self.env.context.get('default_contract_id')
        if contract_id:
            contract = self.env['kgrn.recurring.contract'].browse(contract_id)
            schedule = contract.get_payment_schedule(limit=6)
            schedule_rows = ''.join(
                f'<tr><td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;">'
                f'{d.strftime("%d %b %Y")}</td>'
                f'<td style="padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">'
                f'{contract.currency_id.symbol or contract.currency_id.name} '
                f'{contract.amount:,.2f}</td></tr>'
                for d in schedule
            )
            portal_url = contract.portal_url or ''
            res.update({
                'subject': (
                    f'Action Required: Set Up Your Recurring Payment – {contract.name}'
                ),
                'body_html': f'''
<div style="font-family:Segoe UI,Arial,sans-serif;max-width:600px;margin:0 auto;color:#1f2937;">
  <div style="background:linear-gradient(135deg,#0d2b45,#1a4f72);padding:32px 40px;border-radius:12px 12px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">KGRN Chartered Accountants LLC</h1>
    <p style="color:rgba(255,255,255,0.7);margin:6px 0 0;font-size:13px;letter-spacing:1px;text-transform:uppercase;">
      Recurring Payment Setup
    </p>
  </div>
  <div style="background:#fff;padding:36px 40px;border:1px solid #e5e7eb;border-top:none;">
    <p style="font-size:16px;margin:0 0 16px;">Dear <strong>{contract.customer_id.name}</strong>,</p>
    <p style="color:#4b5563;line-height:1.6;margin:0 0 24px;">
      We have set up a <strong>{contract._get_frequency_label()}</strong> recurring payment
      of <strong>{contract.currency_id.symbol or contract.currency_id.name} {contract.amount:,.2f}</strong>
      on your account (Reference: <strong>{contract.name}</strong>).
      To activate this arrangement, please register your payment card securely using the link below.
    </p>

    <!-- Schedule preview -->
    <div style="margin:0 0 28px;">
      <h3 style="font-size:14px;font-weight:600;color:#0d2b45;margin:0 0 10px;text-transform:uppercase;letter-spacing:0.5px;">
        Upcoming Payment Schedule
      </h3>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:8px 12px;text-align:left;color:#374151;font-weight:600;">Payment Date</th>
            <th style="padding:8px 12px;text-align:right;color:#374151;font-weight:600;">Amount</th>
          </tr>
        </thead>
        <tbody>{schedule_rows}</tbody>
      </table>
      {'<p style="font-size:12px;color:#9ca3af;margin:6px 0 0;">* Showing first 6 payments. Full schedule available on the portal.</p>' if len(schedule) == 6 else ''}
    </div>

    <!-- CTA Button -->
    <div style="text-align:center;margin:28px 0;">
      <a href="{portal_url}"
         style="display:inline-block;background:linear-gradient(135deg,#0d2b45,#1a4f72);
                color:#fff;text-decoration:none;padding:14px 36px;border-radius:8px;
                font-weight:600;font-size:15px;letter-spacing:0.3px;">
        Register Payment Card Securely
      </a>
    </div>
    <p style="font-size:12px;color:#9ca3af;text-align:center;margin:0 0 24px;">
      Or copy this link: <a href="{portal_url}" style="color:#1a4f72;">{portal_url}</a>
    </p>

    <div style="border-top:1px solid #e5e7eb;padding-top:20px;font-size:13px;color:#6b7280;">
      <p style="margin:0 0 8px;"><strong>Contract:</strong> {contract.name}</p>
      <p style="margin:0 0 8px;"><strong>Frequency:</strong> {contract._get_frequency_label()}</p>
      <p style="margin:0 0 8px;"><strong>Amount:</strong> {contract.currency_id.symbol or contract.currency_id.name} {contract.amount:,.2f} per period</p>
      <p style="margin:0 0 8px;"><strong>Start Date:</strong> {contract.start_date.strftime("%d %b %Y") if contract.start_date else "—"}</p>
      <p style="margin:0;"><strong>End Date:</strong> {contract.end_date.strftime("%d %b %Y") if contract.end_date else "—"}</p>
    </div>
  </div>
  <div style="background:#f9fafb;padding:20px 40px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;text-align:center;">
    <p style="font-size:12px;color:#9ca3af;margin:0;">
      This is an automated message from KGRN Chartered Accountants LLC.<br/>
      If you did not request this, please contact us immediately.
    </p>
  </div>
</div>
''',
            })
        return res

    def action_send(self):
        self.ensure_one()
        contract = self.contract_id
        if not self.recipient_email:
            raise UserError(_('Please provide a recipient email address.'))

        mail_values = {
            'subject': self.subject,
            'body_html': self.body_html,
            'email_to': self.recipient_email,
            'email_from': self.env.company.email or self.env.user.email,
            'res_id': contract.id,
            'model': 'kgrn.recurring.contract',
        }
        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send(raise_exception=False)

        contract.write({
            'portal_link_sent': True,
            'portal_link_sent_date': fields.Datetime.now(),
        })
        contract.message_post(
            body=_(
                'Portal link sent to <strong>%s</strong> (%s).'
            ) % (contract.customer_id.name, self.recipient_email),
            subtype_xmlid='mail.mt_note',
        )
        return {'type': 'ir.actions.act_window_close'}
