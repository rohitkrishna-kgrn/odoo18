from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid


class AmlHitWizard(models.TransientModel):
    _name = 'aml.hit.wizard'
    _description = 'AML HIT Detected – Request Additional Documents Wizard'

    request_id = fields.Many2one('aml.request', string='AML Request', required=True, readonly=True)
    doc_line_ids = fields.One2many('aml.hit.wizard.line', 'wizard_id', string='Documents Required')

    def action_send_additional_form(self):
        self.ensure_one()
        if not self.doc_line_ids:
            raise UserError(_("Please add at least one document name before sending."))

        aml = self.request_id
        partner = aml.partner_id

        if not partner.email:
            raise UserError(_("The client does not have an email address."))

        # Generate a fresh additional access token
        additional_token = uuid.uuid4().hex
        aml.sudo().write({'additional_access_token': additional_token})

        # Create aml.hit.document records from wizard lines
        self.env['aml.hit.document'].sudo().search([
            ('request_id', '=', aml.id), ('submitted', '=', False)
        ]).unlink()

        for idx, line in enumerate(self.doc_line_ids):
            self.env['aml.hit.document'].sudo().create({
                'request_id': aml.id,
                'sequence': (idx + 1) * 10,
                'document_name': line.document_name,
            })

        # Build the additional form URL
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        form_url = '%s/aml/additional/%s' % (base_url, additional_token)

        # Send email
        doc_list_html = '<ul>' + ''.join(
            '<li>%s</li>' % line.document_name for line in self.doc_line_ids
        ) + '</ul>'

        body = _(
            "<p>Dear %s,</p>"
            "<p>During our AML review of your KYC submission, we have identified that "
            "additional documentation is required. Please provide the following documents:</p>"
            "%s"
            "<p>Please click the link below to upload the required documents:</p>"
            "<p><a href='%s' style='background:#d32f2f;color:#fff;padding:10px 20px;"
            "text-decoration:none;border-radius:4px;display:inline-block;margin:10px 0;'>"
            "Upload Additional Documents</a></p>"
            "<p>This is a time-sensitive request. Please respond at your earliest convenience.</p>"
            "<p>Regards,<br/>KGRN AML Team</p>"
        ) % (partner.name, doc_list_html, form_url)

        self.env['mail.mail'].sudo().create({
            'subject': _("Action Required: Additional Documents for AML Review – %s") % aml.name,
            'body_html': body,
            'email_to': partner.email,
            'author_id': self.env.user.partner_id.id,
        }).send()

        aml.message_post(
            body=_("Additional document request sent to client (%s). Documents requested: %s") % (
                partner.email,
                ', '.join(line.document_name for line in self.doc_line_ids),
            )
        )

        return {'type': 'ir.actions.act_window_close'}


class AmlHitWizardLine(models.TransientModel):
    _name = 'aml.hit.wizard.line'
    _description = 'AML HIT Wizard – Document Line'

    wizard_id = fields.Many2one('aml.hit.wizard', required=True, ondelete='cascade')
    document_name = fields.Char(string='Document Name', required=True)
