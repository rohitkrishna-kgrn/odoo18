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
            portal_url = contract.portal_url or ''
            sym = contract.currency_id.symbol or contract.currency_id.name

            # Build schedule rows — Outlook-safe table rows
            schedule_rows = ''
            for i, d in enumerate(schedule):
                bg = ' bgcolor="#f9fafb" style="background-color:#f9fafb;' if i % 2 == 0 else ' style="'
                schedule_rows += (
                    f'<tr>'
                    f'<td{bg}padding:9px 14px;font-size:13px;color:#374151;'
                    f'font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
                    f'border-bottom:1px solid #e5e7eb;">'
                    f'{d.strftime("%d %b %Y")}'
                    f'</td>'
                    f'<td{bg}padding:9px 14px;font-size:13px;color:#374151;'
                    f'font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;'
                    f'border-bottom:1px solid #e5e7eb;text-align:right;">'
                    f'{sym}&#160;{contract.amount:,.2f}'
                    f'</td>'
                    f'</tr>'
                )

            more_note = (
                f'<tr><td colspan="2" style="padding:8px 14px;font-size:11px;'
                f'color:#9ca3af;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">'
                f'+ more payments until {contract.end_date.strftime("%d %b %Y")}'
                f'</td></tr>'
            ) if len(schedule) >= 6 else ''

            start_str = contract.start_date.strftime('%d %b %Y') if contract.start_date else '—'
            end_str   = contract.end_date.strftime('%d %b %Y')   if contract.end_date   else '—'

            body = f'''<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <meta name="x-apple-disable-message-reformatting"/>
  <title>Recurring Payment Setup</title>
  <!--[if mso]>
  <xml>
    <o:OfficeDocumentSettings>
      <o:AllowPNG/>
      <o:PixelsPerInch>96</o:PixelsPerInch>
    </o:OfficeDocumentSettings>
  </xml>
  <![endif]-->
  <style>
    body, table, td {{ -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
    table, td {{ mso-table-lspace:0pt; mso-table-rspace:0pt; }}
    body {{ margin:0; padding:0; background-color:#f0f2f5; }}
    a {{ color:#1a4f72; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f0f2f5;">
<table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color:#f0f2f5;">
  <tr>
    <td align="center" style="padding:24px 12px;">

      <!--[if mso]><table role="presentation" cellpadding="0" cellspacing="0" width="600"><tr><td><![endif]-->
      <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="600" style="max-width:600px;">

        <!-- HEADER -->
        <tr>
          <td bgcolor="#0d2b45" style="background-color:#0d2b45;padding:28px 36px;border-radius:12px 12px 0 0;mso-border-radius-topright:12px;mso-border-radius-topleft:12px;">
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td>
                  <h1 style="color:#ffffff;margin:0 0 4px 0;font-size:20px;font-weight:700;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;line-height:1.3;">
                    KGRN Chartered Accountants LLC
                  </h1>
                  <p style="color:#a8c4d8;margin:0;font-size:12px;letter-spacing:1px;text-transform:uppercase;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
                    Recurring Payment Setup
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- BODY -->
        <tr>
          <td bgcolor="#ffffff" style="background-color:#ffffff;border-left:1px solid #e5e7eb;border-right:1px solid #e5e7eb;padding:32px 36px;">

            <p style="margin:0 0 16px 0;font-size:15px;color:#1f2937;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              Dear <strong>{contract.customer_id.name}</strong>,
            </p>
            <p style="color:#4b5563;line-height:1.65;margin:0 0 24px 0;font-size:14px;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              We have set up a <strong>{contract._get_frequency_label()}</strong> recurring payment of
              <strong>{sym}&#160;{contract.amount:,.2f}</strong> on your account
              (Reference: <strong>{contract.name}</strong>).
              To activate this arrangement, please register your payment card securely using the button below.
            </p>

            <!-- Schedule heading -->
            <p style="margin:0 0 8px 0;font-size:12px;font-weight:700;color:#0d2b45;letter-spacing:0.8px;text-transform:uppercase;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              Upcoming Payment Schedule
            </p>

            <!-- Schedule table -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;margin:0 0 8px 0;border:1px solid #e5e7eb;">
              <tr>
                <td bgcolor="#0d2b45" width="55%" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;letter-spacing:0.4px;text-transform:uppercase;">
                  Payment Date
                </td>
                <td bgcolor="#0d2b45" style="background-color:#0d2b45;padding:9px 14px;font-size:12px;font-weight:700;color:#ffffff;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;letter-spacing:0.4px;text-transform:uppercase;text-align:right;">
                  Amount
                </td>
              </tr>
              {schedule_rows}
              {more_note}
            </table>

            <p style="margin:0 0 28px 0;font-size:12px;color:#9ca3af;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              * Payments are deducted automatically on the dates shown above.
            </p>

            <!-- CTA Button -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 20px 0;">
              <tr>
                <td align="center">
                  <!--[if mso]>
                  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word"
                    href="{portal_url}"
                    style="height:48px;v-text-anchor:middle;width:320px;"
                    arcsize="10%" stroke="f" fillcolor="#1a4f72">
                    <w:anchorlock/>
                    <center style="color:#ffffff;font-family:Arial,Helvetica,sans-serif;font-size:15px;font-weight:bold;">
                      Register Payment Card Securely
                    </center>
                  </v:roundrect>
                  <![endif]-->
                  <!--[if !mso]><!-->
                  <a href="{portal_url}"
                     style="background-color:#1a4f72;border-radius:8px;color:#ffffff;display:inline-block;
                            font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;font-size:15px;font-weight:700;
                            line-height:1;padding:14px 32px;text-align:center;text-decoration:none;
                            -webkit-text-size-adjust:none;mso-hide:all;">
                    Register Payment Card Securely
                  </a>
                  <!--<![endif]-->
                </td>
              </tr>
            </table>

            <p style="text-align:center;font-size:12px;color:#9ca3af;margin:0 0 28px 0;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              Or copy this link into your browser:<br/>
              <a href="{portal_url}" style="color:#1a4f72;word-break:break-all;">{portal_url}</a>
            </p>

            <!-- Divider -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 20px 0;">
              <tr><td style="border-top:1px solid #e5e7eb;font-size:0;line-height:0;">&nbsp;</td></tr>
            </table>

            <!-- Contract summary -->
            <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td width="50%" style="padding:4px 0;vertical-align:top;">
                  <p style="margin:0;font-size:12px;color:#6b7280;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
                    <strong style="color:#374151;">Contract:</strong><br/>{contract.name}
                  </p>
                </td>
                <td width="50%" style="padding:4px 0;vertical-align:top;">
                  <p style="margin:0;font-size:12px;color:#6b7280;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
                    <strong style="color:#374151;">Frequency:</strong><br/>{contract._get_frequency_label()}
                  </p>
                </td>
              </tr>
              <tr>
                <td width="50%" style="padding:8px 0 4px;vertical-align:top;">
                  <p style="margin:0;font-size:12px;color:#6b7280;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
                    <strong style="color:#374151;">Amount per Period:</strong><br/>{sym}&#160;{contract.amount:,.2f}
                  </p>
                </td>
                <td width="50%" style="padding:8px 0 4px;vertical-align:top;">
                  <p style="margin:0;font-size:12px;color:#6b7280;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
                    <strong style="color:#374151;">Period:</strong><br/>{start_str} &ndash; {end_str}
                  </p>
                </td>
              </tr>
            </table>

          </td>
        </tr>

        <!-- FOOTER -->
        <tr>
          <td bgcolor="#f9fafb" align="center" style="background-color:#f9fafb;padding:18px 36px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;mso-border-radius-bottomleft:12px;mso-border-radius-bottomright:12px;">
            <p style="font-size:11px;color:#9ca3af;margin:0 0 4px 0;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              This email was sent by KGRN Chartered Accountants LLC as part of a recurring payment arrangement.
            </p>
            <p style="font-size:11px;color:#9ca3af;margin:0;font-family:\'Segoe UI\',Arial,Helvetica,sans-serif;">
              If you did not expect this email, please contact us immediately. Do not share this link with anyone.
            </p>
          </td>
        </tr>

      </table>
      <!--[if mso]></td></tr></table><![endif]-->

    </td>
  </tr>
</table>
</body>
</html>'''

            res.update({
                'subject': f'Action Required: Set Up Your Recurring Payment \u2013 {contract.name}',
                'body_html': body,
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
