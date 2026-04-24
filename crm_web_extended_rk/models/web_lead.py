from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import date


class WebLead(models.Model):
    _name = 'crm.web.lead'
    _description = 'Web Lead Intake'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Name', required=True, tracking=True)
    contact_number = fields.Char(string='Contact Number', tracking=True)
    email = fields.Char(string='Email', tracking=True)
    body = fields.Text(string='Message / Body', tracking=True)
    service = fields.Char(string='Service', tracking=True)
    form_data = fields.Text(string='Form Data (JSON)')
    state = fields.Selection([
        ('new', 'New'),
        ('allocated', 'Allocated'),
        ('converted', 'Converted'),
    ], default='new', string='Status', tracking=True)
    allocated_user_ids = fields.Many2many(
        'res.users',
        'crm_web_lead_user_rel',
        'lead_id',
        'user_id',
        string='Allocated To',
        tracking=True,
    )
    crm_lead_ids = fields.One2many('crm.lead', 'web_lead_id', string='CRM Leads')
    crm_lead_count = fields.Integer(compute='_compute_crm_lead_count', string='Leads')

    @api.depends('crm_lead_ids')
    def _compute_crm_lead_count(self):
        for rec in self:
            rec.crm_lead_count = len(rec.crm_lead_ids)

    def action_allocate(self):
        """Open wizard to allocate selected web leads to users."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Allocate Leads'),
            'res_model': 'crm.web.lead.allocate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_web_lead_ids': self.ids},
        }

    def action_view_crm_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Leads'),
            'res_model': 'crm.lead',
            'view_mode': 'list,form',
            'domain': [('web_lead_id', 'in', self.ids)],
        }

    def _create_crm_leads(self, user):
        """Create one crm.lead for a given user from this web lead."""
        self.ensure_one()
        IrConfigParam = self.env['ir.config_parameter'].sudo()
        stage = self.env['crm.stage'].search([('sequence', '=', 1)], limit=1)
        if not stage:
            stage = self.env['crm.stage'].search([], order='sequence asc', limit=1)

        # Resolve or create partner
        partner = self.env['res.partner'].search(
            [('email', '=', self.email)], limit=1
        ) if self.email else None
        if not partner:
            partner = self.env['res.partner'].create({
                'name': self.name,
                'mobile': self.contact_number,
                'email': self.email,
                'is_company': True,
            })

        # Find existing SEO tag only — do not create if missing
        seo_tag = self.env['crm.tag'].search([('name', '=ilike', 'SEO')], limit=1)
        tag_ids = [(4, seo_tag.id)] if seo_tag else []

        # Lead name: partner name + service (if any) + current date
        today = date.today().strftime('%d/%m/%Y')
        lead_name_parts = [partner.name]
        if self.service:
            lead_name_parts.append(self.service)
        lead_name_parts.append(today)
        lead_name = ' - '.join(lead_name_parts)

        # Build description (Internal Notes tab)
        note_parts = []
        if self.body:
            note_parts.append(
                '<p><strong>-- message --</strong></p>'
                '<p>%s</p>' % self.body
            )
        other_lines = []
        if self.service:
            other_lines.append('<p>Service: %s</p>' % self.service)
        if self.form_data:
            other_lines.append('<pre>%s</pre>' % self.form_data)
        if other_lines:
            note_parts.append(
                '<p><strong>-- other information --</strong></p>'
                + ''.join(other_lines)
            )

        lead = self.env['crm.lead'].create({
            'name': lead_name,
            'partner_id': partner.id,
            'user_id': user.id,
            'phone': self.contact_number,
            'email_from': self.email,
            'tag_ids': tag_ids,
            'stage_id': stage.id,
            'web_lead_id': self.id,
            'description': ''.join(note_parts),
        })
        return lead


class WebLeadAllocateWizard(models.TransientModel):
    _name = 'crm.web.lead.allocate.wizard'
    _description = 'Allocate Web Leads Wizard'

    web_lead_ids = fields.Many2many('crm.web.lead', string='Web Leads')
    user_ids = fields.Many2many('res.users', string='Assign To', required=True)

    def action_confirm(self):
        if not self.user_ids:
            raise UserError(_('Please select at least one user.'))
        leads_created = self.env['crm.lead']
        for web_lead in self.web_lead_ids:
            web_lead.allocated_user_ids = [(4, u.id) for u in self.user_ids]
            for user in self.user_ids:
                leads_created |= web_lead._create_crm_leads(user)
            web_lead.state = 'allocated'
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Leads Created'),
            'res_model': 'crm.lead',
            'view_mode': 'list,form',
            'domain': [('id', 'in', leads_created.ids)],
        }


class WebLeadApiInfo(models.TransientModel):
    _name = 'crm.web.lead.api.info'
    _description = 'Webhook API Information'

    full_url = fields.Char(string='Endpoint URL')
    method = fields.Char(string='HTTP Method')
    auth = fields.Char(string='Authentication')
    content_type = fields.Char(string='Content-Type')
    sample_custom = fields.Text(string='Custom / Flat JSON')
    sample_elementor = fields.Text(string='Elementor Pro Payload')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', 'https://your-odoo-domain.com'
        )
        res.update({
            'full_url': base.rstrip('/') + '/webhook/web-lead',
            'method': 'POST',
            'auth': 'None — no Authorization header required (public endpoint)',
            'content_type': 'application/json  or  application/x-www-form-urlencoded',
            'sample_custom': (
                '{\n'
                '  "name": "John Doe",\n'
                '  "contact_number": "+971501234567",\n'
                '  "email": "john@example.com",\n'
                '  "body": "I am interested in your services.",\n'
                '  "service": "SEO",\n'
                '  "utm_source": "google",\n'
                '  "utm_campaign": "summer2025"\n'
                '}'
            ),
            'sample_elementor': (
                '{\n'
                '  "fields": [\n'
                '    { "id": "name",         "title": "Name",    "value": "John Doe",                  "type": "text" },\n'
                '    { "id": "email",        "title": "Email",   "value": "john@example.com",           "type": "email" },\n'
                '    { "id": "phone",        "title": "Phone",   "value": "+971501234567",              "type": "tel" },\n'
                '    { "id": "message",      "title": "Message", "value": "I am interested in SEO.",   "type": "textarea" },\n'
                '    { "id": "service",      "title": "Service", "value": "SEO",                       "type": "select" }\n'
                '  ],\n'
                '  "form_name": "Contact Form",\n'
                '  "form_id": "abc123",\n'
                '  "page_url": "https://example.com/contact",\n'
                '  "remote_ip": "1.2.3.4",\n'
                '  "submitted_on": "2026-04-24 10:00:00"\n'
                '}'
            ),
        })
        return res


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    web_lead_id = fields.Many2one('crm.web.lead', string='Web Lead Source', ondelete='set null')
