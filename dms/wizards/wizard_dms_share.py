from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import uuid

_logger = logging.getLogger(__name__)

class WizardDmsShare(models.TransientModel):
    _name = "wizard.dms.share"
    _inherit = "portal.share"
    _description = "Wizard for sharing DMS records"

    email_to = fields.Char(string="To Email", required=True)

    @api.model
    def _selection_target_model(self):
        return [
            (model.model, model.name)
            for model in self.env["ir.model"]
            .sudo()
            .search([("model", "in", ("dms.directory", "dms.file"))])
        ]

    def action_send_share_email(self):
        self.ensure_one()
        if not self.email_to:
            raise UserError("Please provide a recipient email address.")

        # ✅ Make sure the share record exists before accessing token
        if not self.share_id or not self.share_id.access_token:
            raise UserError("Access token is missing. Please save the share first.")

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        share_url = f"{base_url}/dms/public/{self.share_id.access_token}"

        body_html = f"""
            <p>Hello,</p>
            <p>A directory/file has been shared with you. You can access it using the following link:</p>
            <p><a href="{share_url}">{share_url}</a></p>
            <p>You can upload files there without needing to log in.</p>
            <p>Best regards,<br/>Your Company</p>
        """

        mail = self.env['mail.mail'].create({
            'subject': 'Shared Directory/File Link',
            'email_to': self.email_to,
            'body_html': body_html,
        })
        mail.sudo().send()

        return {'type': 'ir.actions.act_window_close'}

class DmsDirectoryShareWizard(models.TransientModel):
    _name = 'dms.directory.share.wizard'
    _description = 'Share DMS Directory Wizard'

    email = fields.Char(string='Email', required=True)
    directory_id = fields.Many2one('dms.directory', string='Directory', required=True)

    def _generate_access_token(self):
        """Generate a unique UUID token."""
        return str(uuid.uuid4())

    def action_send_invite(self):
        self.ensure_one()

        if not self.email:
            raise UserError(_("Please provide an email address."))

        directory = self.directory_id.sudo()

        if not directory.exists():
            raise UserError(_("The selected directory does not exist."))

        # Generate access token if not present
        if not directory.access_token:
            directory.access_token = self._generate_access_token()
            directory.sudo().write({'access_token': directory.access_token})

        access_token = directory.access_token

        # Compose the share URL
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        share_url = f"{base_url}/my/dms/directory/{directory.id}?access_token={access_token}"

        # Compose email body (HTML)
        email_body = f"""
            <!DOCTYPE html>
            <html lang="en" style="font-family: Arial, sans-serif; background-color: #f7f9fc; margin: 0; padding: 0;">
            <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>Folder Access Invitation</title>
            </head>
            <body style="margin:0; padding: 0; background-color: #f7f9fc;">
                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f7f9fc; padding: 30px 0;">
                    <tr>
                        <td align="center">
                            <table width="600" cellpadding="0" cellspacing="0" border="0" style="background-color: #ffffff; border-radius: 6px; box-shadow: 0 0 10px rgba(0,0,0,0.1);">
                                <tr>
                                    <td style="padding: 20px; text-align: center; background-color: #004080; color: #ffffff; border-top-left-radius: 6px; border-top-right-radius: 6px;">
                                        <h1 style="margin: 0; font-size: 24px;">KGRN Chartered Accountants LLC</h1>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 30px; color: #333333; font-size: 16px; line-height: 1.5;">
                                        <p>Hello,</p>
                                        <p>You have been invited to access the folder: <strong>{directory.name}</strong>.</p>
                                        <p>Please click the button below to securely view the folder:</p>
                                        <p style="text-align: center;">
                                            <a href="{share_url}" style="display: inline-block; padding: 12px 25px; background-color: #004080; color: #ffffff; text-decoration: none; border-radius: 4px; font-weight: bold;">
                                                Access Folder
                                            </a>
                                        </p>
                                        <p>If the button above does not work, copy and paste the following link into your browser:</p>
                                        <p style="word-break: break-all;"><a href="{share_url}" style="color: #004080;">{share_url}</a></p>
                                        <p>Best regards,<br/>KGRN Chartered Accountants LLC</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="background-color: #f1f1f1; text-align: center; padding: 15px; font-size: 12px; color: #777777; border-bottom-left-radius: 6px; border-bottom-right-radius: 6px;">
                                        &copy; {fields.Date.today().year} KGRN Chartered Accountants LLC. All rights reserved.
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </table>
            </body>
            </html>
            """

        mail_values = {
            'subject': _('Invitation to access folder %s') % directory.name,
            'body_html': email_body,
            'email_to': self.email,
            'auto_delete': True,  # Optional: delete mail after sending
        }

        mail = self.env['mail.mail'].sudo().create(mail_values)
        mail.send()

        _logger.info(f"Share invite sent to {self.email} for directory {directory.name} (ID: {directory.id})")

        return {'type': 'ir.actions.act_window_close'}