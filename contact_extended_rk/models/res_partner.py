from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    emirates_id = fields.Char(string="Emirates ID")
    passport_number = fields.Char(string="Passport Number")
    company_license_no = fields.Char(string="Company License Number")

    # Form submission tracking
    form_token_ids = fields.One2many('contact.form.token', 'partner_id', string='Form Submissions')
    form_submission_count = fields.Integer(compute='_compute_form_state', string='Forms Sent')
    form_submission_state = fields.Char(compute='_compute_form_state', string='Form Status')
    form_submitted_date = fields.Datetime(compute='_compute_form_state', string='Submitted On')
    latest_form_token_id = fields.Many2one(
        'contact.form.token', compute='_compute_form_state', string='Latest Submission'
    )

    @api.depends('form_token_ids.state', 'form_token_ids.submitted_date')
    def _compute_form_state(self):
        for partner in self:
            tokens = partner.form_token_ids
            partner.form_submission_count = len(tokens)
            submitted = tokens.filtered(lambda t: t.state == 'submitted').sorted(
                'submitted_date', reverse=True
            )
            if submitted:
                partner.form_submission_state = 'submitted'
                partner.form_submitted_date = submitted[0].submitted_date
                partner.latest_form_token_id = submitted[0]
            else:
                pending = tokens.filtered(lambda t: t.state == 'pending')
                partner.form_submission_state = 'pending' if pending else ''
                partner.form_submitted_date = False
                partner.latest_form_token_id = False

    @api.model
    def create(self, vals):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            required_fields = ['phone', 'email', 'street', 'city', 'country_id', 'zip']
            for field in required_fields:
                if not vals.get(field):
                    raise ValidationError(f"The field '{field}' is mandatory and cannot be empty.")
        return super().create(vals)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            required_fields = ['phone', 'email', 'street', 'city', 'country_id', 'zip']
            for field in required_fields:
                if field in vals and not vals.get(field):
                    raise ValidationError(f"The field '{field}' is mandatory and cannot be empty.")
        return super().write(vals)

    def action_send_customer_form(self):
        self.ensure_one()
        if not self.email:
            raise UserError(_("This contact has no email address. Please add one before sending the form."))

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')

        token_record = self.env['contact.form.token'].sudo().create({
            'partner_id': self.id,
            'expiry_date': fields.Datetime.now() + timedelta(days=7),
            'base_url': base_url,
        })

        template = self.env.ref('contact_extended_rk.email_template_customer_form')
        template.sudo().send_mail(
            token_record.id,
            force_send=True,
            email_values={'auto_delete': False},
        )

        expiry_str = token_record.expiry_date.strftime('%d %b %Y') if token_record.expiry_date else 'N/A'
        self.message_post(
            body=_('Customer Information Form sent to %s by %s on %s. Link expires %s.') % (
                self.email,
                self.env.user.name,
                fields.Datetime.now().strftime('%d %b %Y %H:%M'),
                expiry_str,
            ),
            subtype_xmlid='mail.mt_note',
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Form Sent'),
                'message': _('Customer information form has been sent to %s.') % self.email,
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'res.partner',
                    'res_id': self.id,
                    'view_mode': 'form',
                    'target': 'current',
                    'views': [[False, 'form']],
                },
            },
        }

    def action_download_form_submission(self):
        self.ensure_one()
        token = self.latest_form_token_id
        if not token:
            raise UserError(_('No submitted form found for this contact.'))
        return self.env.ref('contact_extended_rk.action_report_customer_form').report_action(token)

    def action_view_form_tokens(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Form Submissions'),
            'res_model': 'contact.form.token',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }
