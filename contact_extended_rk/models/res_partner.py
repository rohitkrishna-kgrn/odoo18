from datetime import timedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from odoo.osv import expression

MIN_SEARCH_CHARS = 4
CREATE_SOURCES = ('crm', 'services')
# Fields a free-text search can target; a search on these needs MIN_SEARCH_CHARS.
TEXT_SEARCH_FIELDS = ('display_name', 'complete_name', 'name', 'email', 'ref', 'vat', 'company_registry')


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

    # ------------------------------------------------------------------
    # Access policy: only Contact Admins browse all contacts
    # ------------------------------------------------------------------
    def _is_contact_admin(self):
        return self.env.su or self.env.user.has_group('contact_extended_rk.group_contact_admin')

    @api.model
    def _search_display_name(self, operator, value):
        """Everyone but Contact Admins must type MIN_SEARCH_CHARS letters before
        any client name matches. Dropdowns, search-bar autocomplete and
        Customer filters all resolve through display_name, so this one hook
        covers them."""
        if (operator.endswith('like') and not self._is_contact_admin()
                and len(value.strip() if isinstance(value, str) else '') < MIN_SEARCH_CHARS):
            return expression.FALSE_DOMAIN
        return super()._search_display_name(operator, value)

    @api.model
    def _domain_pins_contacts(self, domain):
        """True when every branch of the domain names specific ids or carries a
        text search of at least MIN_SEARCH_CHARS letters."""
        tokens = iter(expression.normalize_domain(domain or []))

        def parse():
            token = next(tokens)
            if token == '&':
                left, right = parse(), parse()
                return left or right
            if token == '|':
                left, right = parse(), parse()
                return left and right
            if token == '!':
                parse()
                return False
            field, operator, value = token
            if field == 'id' and operator in ('=', 'in', 'child_of'):
                return bool(value)
            if field in TEXT_SEARCH_FIELDS and operator.endswith('like'):
                return isinstance(value, str) and len(value.strip()) >= MIN_SEARCH_CHARS
            return False

        try:
            return parse()
        except StopIteration:
            return False

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        if not self._is_contact_admin() and not self._domain_pins_contacts(domain):
            return {'length': 0, 'records': []}
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)

    @api.model
    def web_read_group(self, domain, fields, groupby, limit=None, offset=0, orderby=False, lazy=True):
        if not self._is_contact_admin() and not self._domain_pins_contacts(domain):
            return {'groups': [], 'length': 0}
        return super().web_read_group(
            domain, fields, groupby, limit=limit, offset=offset, orderby=orderby, lazy=lazy)

    # ------------------------------------------------------------------
    # No external company suggestions in the contact picker
    # ------------------------------------------------------------------
    # partner_autocomplete queries Odoo's IAP company database and lists
    # companies (Bidfood B.V., ...) that are not in our Contacts at all.
    @api.model
    def autocomplete_by_name(self, query, query_country_id, timeout=15):
        return []

    @api.model
    def autocomplete_by_vat(self, vat, query_country_id, timeout=15):
        return []

    # ------------------------------------------------------------------
    # Contacts are created from CRM or Services only
    # ------------------------------------------------------------------
    def _check_ui_create_allowed(self):
        if self._is_contact_admin() or self.env.context.get('partner_create_source') in CREATE_SOURCES:
            return
        raise UserError(_(
            "Contacts can only be created from the CRM or Services apps. "
            "Please create the contact from a lead or a quotation."))

    @api.model
    def name_create(self, name):
        self._check_ui_create_allowed()
        return super().name_create(name)

    def web_save(self, vals, specification, next_id=None):
        if not self:
            self._check_ui_create_allowed()
        return super().web_save(vals, specification, next_id=next_id)

    def copy(self, default=None):
        self._check_ui_create_allowed()
        return super().copy(default)

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
