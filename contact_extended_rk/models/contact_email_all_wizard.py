from datetime import timedelta
from odoo import models, fields, api, _


class ContactEmailAllWizard(models.TransientModel):
    _name = 'contact.email.all.wizard'
    _description = 'Send Customer Information Form to All Contacts'

    contact_count = fields.Integer(
        string='Contacts with Email',
        compute='_compute_contact_count',
    )
    public_form_url = fields.Char(
        string='Public Form URL',
        compute='_compute_public_form_url',
    )

    @api.depends()
    def _compute_contact_count(self):
        count = self.env['res.partner'].search_count([
            ('email', '!=', False),
            ('email', '!=', ''),
        ])
        for wizard in self:
            wizard.contact_count = count

    @api.depends()
    def _compute_public_form_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        for wizard in self:
            wizard.public_form_url = '%s/customer-form' % base

    def action_send_all(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')

        partners = self.env['res.partner'].search([
            ('email', '!=', False),
            ('email', '!=', ''),
        ])
        template = self.env.ref('contact_extended_rk.email_template_customer_form')
        sent = 0
        for partner in partners:
            token_record = self.env['contact.form.token'].sudo().create({
                'partner_id': partner.id,
                'expiry_date': fields.Datetime.now() + timedelta(days=7),
                'base_url': base_url,
            })
            template.sudo().send_mail(
                token_record.id,
                force_send=True,
                email_values={'auto_delete': False},
            )
            sent += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Emails Sent'),
                'message': _('Customer Information Form sent to %d contacts.') % sent,
                'type': 'success',
                'sticky': True,
            },
        }
