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
            hit_doc = self.env['aml.hit.document'].sudo().create({
                'request_id': aml.id,
                'sequence': (idx + 1) * 10,
                'document_name': line.document_name,
                'staff_note': line.description or False,
            })
            if line.reference_file:
                ref_attachment = self.env['ir.attachment'].sudo().create({
                    'name': line.reference_filename or ('Reference - %s' % line.document_name),
                    'datas': line.reference_file,
                    'res_model': 'aml.hit.document',
                    'res_id': hit_doc.id,
                })
                ref_attachment.generate_access_token()
                hit_doc.staff_sample_attachment_id = ref_attachment.id

        # Build the additional form URL
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        form_url = '%s/aml/additional/%s' % (base_url, additional_token)

        # Send email
        doc_table = aml._email_list_table(
            headers=[_('Document')],
            rows=[[line.document_name] for line in self.doc_line_ids],
        )

        body_html = (
            '<p style="color:%s;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;margin:0 0 16px;">'
            'Dear <strong>%s</strong>,</p>'
            '<p style="color:#555555;font-family:Arial,sans-serif;font-size:14px;line-height:1.75;margin:0 0 14px;">'
            'During our AML review of your KYC submission, we have identified that additional '
            'documentation is required. Please provide the following documents:</p>'
            '%s%s'
            '<p style="color:#888888;font-family:Arial,sans-serif;font-size:13px;margin:0;">'
            'This is a time-sensitive request. Please respond at your earliest convenience.</p>'
        ) % (
            aml._EMAIL_NAVY, partner.name, doc_table,
            aml._email_cta_button(_('Upload Additional Documents'), form_url),
        )

        full_body = aml._email_shell(
            title=_('Additional Documents Required'),
            subtitle=_('AML HIT Review – %s') % aml.name,
            body_html=body_html,
        )

        self.env['mail.mail'].sudo().create({
            'subject': _("Action Required: Additional Documents for AML Review – %s") % aml.name,
            'body_html': full_body,
            'email_from': aml._get_mail_from(),
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
    description = fields.Char(string='Description / Guidance for Client',
        help='Optional extra detail about what exactly is needed for this document, shown to the client on the upload form and in the request email.')
    reference_file = fields.Binary(string='Reference File')
    reference_filename = fields.Char(string='Reference File Name')
