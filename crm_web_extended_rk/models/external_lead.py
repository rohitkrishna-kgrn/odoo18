import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CrmExternalLead(models.Model):
    """Categorised lead intake coming from an external automation (e.g. Meta Ads
    pipeline that pre-classifies each submission as Qualified, Spam or a
    Technical/processing error needing manual review)."""

    _name = 'crm.external.lead'
    _description = 'External CRM Lead Intake'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Name', required=True, tracking=True)
    email = fields.Char(string='Work Email', tracking=True)
    phone = fields.Char(string='Work Phone', tracking=True)
    company = fields.Char(string='Company', tracking=True)
    city = fields.Char(string='City')
    company_size = fields.Char(string='Company Size')
    currently_uses_erp = fields.Char(string='Currently Uses ERP')
    plans_to_implement = fields.Char(string='Plans to Implement e-Invoicing')
    service_interest = fields.Char(string='Service Interest')
    source = fields.Char(string='Source', default='Meta Ads', tracking=True)

    category = fields.Selection([
        ('qualified', 'Qualified'),
        ('spam', 'SPAM / Irrelevant'),
        ('technical', 'Technical Issue'),
    ], string='Category', required=True, default='qualified', tracking=True)

    # Category specific context
    ai_reason = fields.Text(string='AI Reason')
    validity_passed = fields.Boolean(string='Validity Passed')
    service_relevant = fields.Boolean(string='Service Relevant')
    detail = fields.Char(string='Detail')
    execution_id = fields.Char(string='Execution ID')

    raw_payload = fields.Text(string='Raw Payload (JSON)')

    state = fields.Selection([
        ('new', 'New'),
        ('assigned', 'Assigned'),
    ], default='new', string='Status', tracking=True)
    user_id = fields.Many2one('res.users', string='Assigned Salesperson', tracking=True)
    crm_lead_id = fields.Many2one('crm.lead', string='CRM Lead', ondelete='set null')

    # ── Actions ──────────────────────────────────────────────────────────────

    def action_assign(self):
        """Open the wizard asking which salesperson to allocate to."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assign To Salesperson'),
            'res_model': 'crm.external.lead.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_lead_ids': self.ids},
        }

    def action_view_crm_lead(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('CRM Lead'),
            'res_model': 'crm.lead',
            'res_id': self.crm_lead_id.id,
            'view_mode': 'form',
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_metaads_tag(self):
        """Return the 'Meta Ads' crm.tag, creating it on first use."""
        Tag = self.env['crm.tag']
        tag = Tag.search([('name', '=ilike', 'Meta Ads')], limit=1)
        if not tag:
            tag = Tag.create({'name': 'Meta Ads'})
        return tag

    def _get_or_create_partner(self):
        self.ensure_one()
        Partner = self.env['res.partner']
        partner = False
        if self.email:
            partner = Partner.search([('email', '=', self.email)], limit=1)
        if not partner:
            partner = Partner.create({
                'name': self.company or self.name,
                'company_name': self.company or False,
                'is_company': bool(self.company),
                'phone': self.phone,
                'email': self.email,
                'city': self.city,
            })
        return partner

    def _build_internal_notes(self):
        """Everything that is not a mapped lead field goes to internal notes."""
        self.ensure_one()
        rows = [
            ('Source', self.source),
            ('Category', dict(self._fields['category'].selection).get(self.category)),
            ('Company', self.company),
            ('City', self.city),
            ('Company Size', self.company_size),
            ('Currently Uses ERP', self.currently_uses_erp),
            ('Plans to Implement e-Invoicing', self.plans_to_implement),
            ('Service Interest', self.service_interest),
            ('AI Reason', self.ai_reason),
            ('Detail', self.detail),
            ('Execution ID', self.execution_id),
        ]
        if self.category == 'spam':
            rows.append(('Validity Passed', 'Yes' if self.validity_passed else 'No'))
            rows.append(('Service Relevant', 'Yes' if self.service_relevant else 'No'))
        html = ''.join(
            '<p><strong>%s:</strong> %s</p>' % (label, val)
            for label, val in rows if val not in (None, '', False)
        )
        return html

    def _assign_to_user(self, user, date_deadline=False):
        """Create the contact + crm.lead in the salesperson pipeline and notify."""
        self.ensure_one()
        if self.crm_lead_id:
            raise UserError(_('Lead "%s" is already assigned.') % self.name)

        partner = self._get_or_create_partner()
        tag = self._get_metaads_tag()
        stage = self.env['crm.stage'].search([], order='sequence asc', limit=1)

        lead = self.env['crm.lead'].create({
            'name': self.name,
            'partner_id': partner.id,
            'contact_name': self.name,
            'partner_name': self.company or False,
            'phone': self.phone,
            'email_from': self.email,
            'city': self.city,
            'user_id': user.id,
            'date_deadline': date_deadline or fields.Date.context_today(self),
            'tag_ids': [(4, tag.id)],
            'stage_id': stage.id if stage else False,
            'description': self._build_internal_notes(),
        })

        self.write({
            'state': 'assigned',
            'user_id': user.id,
            'crm_lead_id': lead.id,
        })

        # Email notification to the salesperson.
        lead.message_subscribe(partner_ids=user.partner_id.ids)
        lead.message_post(
            body=_('A new lead "%s" has been assigned to you.') % self.name,
            partner_ids=user.partner_id.ids,
            subject=_('New lead assigned: %s') % self.name,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return lead


class CrmExternalLeadAssignWizard(models.TransientModel):
    _name = 'crm.external.lead.assign.wizard'
    _description = 'Assign External Lead Wizard'

    lead_ids = fields.Many2many('crm.external.lead', string='Leads')
    user_id = fields.Many2one('res.users', string='Salesperson', required=True)
    date_deadline = fields.Date(
        string='Expected Closing Date',
        default=lambda self: fields.Date.context_today(self) + timedelta(days=30),
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.user_id:
            raise UserError(_('Please select a salesperson.'))
        leads = self.env['crm.lead']
        for lead in self.lead_ids:
            leads |= lead._assign_to_user(self.user_id, self.date_deadline)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assigned CRM Leads'),
            'res_model': 'crm.lead',
            'view_mode': 'list,form',
            'domain': [('id', 'in', leads.ids)],
        }


class CrmExternalLeadApiInfo(models.TransientModel):
    _name = 'crm.external.lead.api.info'
    _description = 'External Lead Webhook API Information'

    full_url = fields.Char(string='Endpoint URL')
    method = fields.Char(string='HTTP Method')
    auth = fields.Char(string='Authentication')
    content_type = fields.Char(string='Content-Type')
    sample_qualified = fields.Text(string='Qualified Payload')
    sample_spam = fields.Text(string='SPAM / Irrelevant Payload')
    sample_technical = fields.Text(string='Technical Issue Payload')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', 'https://your-odoo-domain.com'
        )
        res.update({
            'full_url': base.rstrip('/') + '/webhook/crm-external-lead',
            'method': 'POST',
            'auth': 'None — public endpoint (no Authorization header required)',
            'content_type': 'application/json',
            'sample_qualified': json.dumps({
                'category': 'qualified',
                'source': 'Meta Ads',
                'name': 'Balamurugan',
                'email': 'balamurugan@kgrnaudit.com',
                'phone': '+971554785845',
                'company': 'Avere Management LLC',
                'city': 'Dubai',
                'company_size': '11-50 employees',
                'currently_uses_erp': 'Odoo',
                'plans_to_implement': 'Within 1-3 months',
                'service_interest': 'e-Invoicing / ERP implementation enquiry',
                'ai_reason': 'Valid UAE business with complete contact details and '
                             'high intent e-invoicing/ERP implementation request.',
            }, indent=2),
            'sample_spam': json.dumps({
                'category': 'spam',
                'source': 'Meta Ads',
                'name': 'dfvf',
                'email': 'dsc@kfv.com',
                'phone': '+9718856215',
                'company': 'sdfcdfs',
                'city': 'Dubai',
                'company_size': '11-50 employees',
                'currently_uses_erp': 'Oracle NetSuite',
                'plans_to_implement': 'Immediately',
                'service_interest': 'e-Invoicing / ERP implementation enquiry',
                'ai_reason': 'Name and company appear gibberish, failing validity check.',
                'validity_passed': False,
                'service_relevant': False,
            }, indent=2),
            'sample_technical': json.dumps({
                'category': 'technical',
                'source': 'Meta Ads',
                'name': 'dfsvdscvd',
                'email': 'sdcfdfv@fvimsr.com',
                'phone': '+971551651615',
                'company': 'dsfvds',
                'city': 'sdsd',
                'company_size': '11-50 employees',
                'currently_uses_erp': 'Tally',
                'plans_to_implement': 'Within 1-3 months',
                'service_interest': 'e-Invoicing / ERP implementation enquiry',
                'detail': 'Unhandled / unexpected outcome',
                'execution_id': '7',
            }, indent=2),
        })
        return res
