from odoo import models, fields, api, _
from odoo.exceptions import UserError
import uuid


class AmlAdditionalDocsWizard(models.TransientModel):
    _name = 'aml.additional.docs.wizard'
    _description = 'AML Additional Documents – Request Wizard'

    request_id = fields.Many2one('aml.request', string='AML Request', required=True, readonly=True)
    doc_line_ids = fields.One2many('aml.additional.docs.wizard.line', 'wizard_id', string='Documents Required')

    def action_send_mail(self):
        self.ensure_one()
        if not self.doc_line_ids:
            raise UserError(_("Please add at least one document name before sending."))

        aml = self.request_id
        partner = aml.partner_id
        from_no_hit = aml.state == 'no_hit'

        if not partner.email:
            raise UserError(_("The client does not have an email address."))

        # Generate a fresh additional access token (overwrites any previous one)
        additional_token = uuid.uuid4().hex
        aml.sudo().write({'additional_access_token': additional_token})

        # Remove any previous un-submitted hit documents and create new ones
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

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        form_url = '%s/aml/additional/%s' % (base_url, additional_token)

        doc_table = aml._email_list_table(
            headers=[_('Document')],
            rows=[[line.document_name] for line in self.doc_line_ids],
        )

        body_html = (
            '<p style="color:%s;font-family:Arial,sans-serif;font-size:14px;line-height:1.6;margin:0 0 16px;">'
            'Dear <strong>%s</strong>,</p>'
            '<p style="color:#555555;font-family:Arial,sans-serif;font-size:14px;line-height:1.75;margin:0 0 14px;">'
            'As part of the ongoing AML review of your KYC submission, we require the following '
            'additional documents:</p>'
            '%s%s'
            '<p style="color:#888888;font-family:Arial,sans-serif;font-size:13px;margin:0;">'
            'This is a time-sensitive request. Please respond at your earliest convenience.</p>'
        ) % (
            aml._EMAIL_NAVY, partner.name, doc_table,
            aml._email_cta_button(_('Upload Additional Documents'), form_url),
        )

        full_body = aml._email_shell(
            title=_('Additional Documents Required'),
            subtitle=_('AML Review – %s') % aml.name,
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

        if from_no_hit:
            aml.write({
                'state': 'additional_info',
                'additional_info_enabled': True,
            })
            aml.message_post(
                body=_("Status changed to Additional Info Received: additional documents requested from client while in No HIT status.")
            )
            aml._notify_aml_managers_and_management(
                subject=_("AML Request %s – Additional Info Requested (from No HIT)") % aml.name,
                intro=_("AML Request <strong>%s</strong> has moved to <strong>Additional Info Received</strong> status. "
                        "Additional documents were requested from the client while the request was in No HIT status.") % aml.name,
                kv_rows=[
                    (_('Client'), partner.name),
                    (_('Status'), _('Additional Info Received')),
                ],
            )

        return {'type': 'ir.actions.act_window_close'}


class AmlAdditionalDocsWizardLine(models.TransientModel):
    _name = 'aml.additional.docs.wizard.line'
    _description = 'AML Additional Documents Wizard – Document Line'

    wizard_id = fields.Many2one('aml.additional.docs.wizard', required=True, ondelete='cascade')
    document_name = fields.Char(string='Document Name', required=True)
    description = fields.Char(string='Description / Guidance for Client',
        help='Optional extra detail about what exactly is needed for this document, shown to the client on the upload form and in the request email.')
    reference_file = fields.Binary(string='Reference File')
    reference_filename = fields.Char(string='Reference File Name')
