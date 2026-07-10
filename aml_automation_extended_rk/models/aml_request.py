from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta
import uuid
import base64
from io import BytesIO


class AmlRequest(models.Model):
    _name = 'aml.request'
    _description = 'AML Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    # =========================================================================
    # Core Fields
    # =========================================================================
    name = fields.Char(
        string='AML Reference', default='New', readonly=True, copy=False, tracking=True,
        index=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New Request'),
        ('accepted', 'Accepted'),
        ('in_progress', 'In Progress'),
        ('no_hit', 'No HIT'),
        ('hit_detected', 'HIT Detected'),
        ('additional_info', 'Additional Info Received'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('bypassed', 'Bypassed'),
        ('cancelled', 'Cancelled'),
    ], default='draft', tracking=True, string='Status', index=True,
       group_expand='_group_expand_states')

    sale_order_id = fields.Many2one('sale.order', string='Sale Order', readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Client', readonly=True, tracking=True)
    kyc_type = fields.Selection([
        ('entity', 'Entity'),
        ('individual', 'Individual'),
    ], string='KYC Type', readonly=True, tracking=True)

    deadline = fields.Datetime(string='Deadline', tracking=True)
    start_datetime = fields.Datetime(string='Start Date & Time', readonly=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    aml_user_id = fields.Many2one('res.users', string='AML Officer', tracking=True)

    # Signature / Declaration
    signature_data = fields.Binary(string='Client Signature', attachment=True)
    signatory_name = fields.Char(string='Signatory Name')
    signatory_designation = fields.Char(string='Designation')
    signed_date = fields.Datetime(string='Signed On', readonly=True)
    accept_declaration = fields.Boolean(string='Declaration Accepted')

    # Additional form (HIT detected flow)
    additional_access_token = fields.Char(string='Additional Form Token', copy=False, index=True)
    additional_info_enabled = fields.Boolean(string='Additional Info Tab Enabled', default=False)
    additional_info_text = fields.Text(string='Additional Information Notes')
    additional_submitted_date = fields.Datetime(string='Additional Info Submitted On')

    # Computed UI flags
    is_aml_manager = fields.Boolean(compute='_compute_user_flags')
    is_aml_user = fields.Boolean(compute='_compute_user_flags')

    # =========================================================================
    # KYC Entity Fields
    # =========================================================================
    ent_entity_name = fields.Char(string='Name of the Entity')
    ent_legal_type = fields.Char(string='Legal Type')
    ent_trading_name = fields.Char(string='Trading Name (if different)')
    ent_date_of_incorporation = fields.Date(string='Date of Incorporation')
    ent_place_of_incorporation = fields.Char(string='Place of Incorporation')
    ent_registration_authority = fields.Char(string='Registration Authority')
    ent_license_number = fields.Char(string='License/Registration Number')
    ent_license_expiry = fields.Date(string='License Expiry')
    ent_registered_address = fields.Text(string='Registered Address')
    ent_business_address = fields.Text(string='Place of Business Address')
    ent_industry_type = fields.Char(string='Industry Type')
    ent_nature_of_business = fields.Text(string='List of business activities as per license')
    ent_source_of_wealth = fields.Text(string='Source of Wealth')
    ent_ownership_complexity = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')], string='Ownership Structure Complexity'
    )
    ent_countries_commercial = fields.Text(string='Is the business is involved in cash payment transactions?')
    ent_high_risk_jurisdiction = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')], string='Is the business is involved in high-risk jurisdiction? (Iran, DPRK - North Korea, Myanmar)'
    )
    # Channel of transaction
    ent_channel_cash = fields.Boolean(string='Cash')
    ent_channel_wire = fields.Boolean(string='Wire Transfers')
    ent_channel_cheque = fields.Boolean(string='Cheque')
    ent_channel_credit = fields.Boolean(string='Credit Cards')
    ent_channel_crypto = fields.Boolean(string='Bitcoins/Cryptocurrencies')
    ent_channel_debit = fields.Boolean(string='Debit Cards')
    # Cash payment threshold
    ent_cash_less_50k = fields.Boolean(string='Less than 50 Thousand AED')
    ent_cash_more_50k = fields.Boolean(string='More than 50 Thousand AED')
    ent_cash_na = fields.Boolean(string='N/A (Cash)')
    ent_top5_suppliers = fields.Text(string='Top 5 Suppliers Countries')
    ent_top5_customers = fields.Text(string='Top 5 Customers Countries')
    # Contact
    ent_contact_name = fields.Char(string='Contact Person Name')
    ent_contact_designation = fields.Char(string='Contact Person Designation')
    ent_contact_email = fields.Char(string='Contact Person Email')
    ent_contact_mobile = fields.Char(string='Contact Person Mobile')
    ent_manager_name = fields.Char(string='Manager Name as per License')
    # Other info
    ent_parent_company_name = fields.Char(string='Parent Company/Head Office Name')
    ent_parent_company_address = fields.Text(string='Parent Company/Head Office Address')
    ent_international_sanctions = fields.Selection(
        [('yes', 'Yes'), ('no', 'No')], string='Is the business subject to sanction from United Nations, United Arab Emirates, DFAC and UK Sanctions'
    )
    # PEP
    ent_pep_shareholder = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Shareholder')
    ent_pep_director = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Director')
    ent_pep_owner = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Owner')
    ent_pep_local_sponsor = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Local Sponsor')
    ent_pep_key_management = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Key Management Personnel')
    ent_pep_officer = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Officer')
    ent_pep_agent = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='PEP - Agent')

    # =========================================================================
    # KYC Individual Fields
    # =========================================================================
    ind_full_name = fields.Char(string='Full Name')
    ind_gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female'), ('other', 'Other')], string='Gender'
    )
    ind_nationality = fields.Char(string='Nationality')
    ind_date_of_birth = fields.Date(string='Date of Birth')
    ind_place_of_birth = fields.Char(string='Place of Birth')
    ind_id_type = fields.Selection([
        ('emirates_id', 'Emirates ID'),
        ('passport', 'Passport'),
        ('other', 'Other'),
    ], string='Type of ID Presented')
    ind_id_type_other = fields.Char(string='Other ID Type')
    ind_id_number = fields.Char(string='Emirates ID / Passport Number')
    ind_issuing_country = fields.Char(string='Issuing Country')
    ind_valid_until = fields.Date(string='Valid Until')
    ind_permanent_address = fields.Text(string='Permanent Residential Address')
    ind_uae_address = fields.Text(string='Current UAE Address (if different)')
    ind_city = fields.Char(string='City')
    ind_country = fields.Char(string='Country')
    ind_mobile = fields.Char(string='Mobile / Telephone No.')
    ind_email = fields.Char(string='Email Address')
    ind_proof_address_type = fields.Selection([
        ('utility_bill', 'Utility Bill'),
        ('bank_statement', 'Bank Statement'),
        ('lease', 'Lease / Title'),
        ('other', 'Other'),
    ], string='Proof of Address Type')
    ind_proof_address_other = fields.Char(string='Other Proof of Address')
    ind_document_date = fields.Date(string='Document Date (not older than 3 months)')
    ind_emirates_id_attached = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Emirates ID Attached')
    ind_passport_attached = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Passport Attached')
    ind_proof_address_attached = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Proof of Address Attached')
    ind_other_id_attached = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Other Govt ID Attached')
    ind_verified_portal = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Verified via Portal/Smart Pass/UAE Pass')
    ind_verified_physically = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Verified Physically by Staff')
    ind_video_kyc = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Video KYC Completed')
    ind_purpose_of_relationship = fields.Char(string='Purpose of Account/Relationship')
    ind_purpose_of_relationship_other = fields.Char(string='Purpose of Relationship (Other)')
    ind_expected_transactions = fields.Text(string='Expected Nature of Transactions')
    ind_monthly_turnover = fields.Char(string='Expected Monthly Turnover/Transaction Value')
    ind_source_of_funds = fields.Text(string='Source of Funds/Income')
    ind_hold_shares_behalf = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Hold Shares on Behalf of Another')
    ind_high_risk_jurisdiction = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='High-Risk Jurisdiction Association')
    ind_anticipated_origin = fields.Text(string='Anticipated Origin of Funds')
    ind_dual_citizenship = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Citizen of More Than One Country')
    ind_dual_citizenship_detail = fields.Text(string='Dual / Multiple Citizenship Details')
    ind_high_net_worth = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='High Net Worth Individual (≥ USD 15m)')
    ind_bank_name = fields.Char(string='Bank Name')
    ind_bank_branch_address = fields.Text(string='Bank Branch Address')
    ind_iban = fields.Char(string='IBAN / Account Number')

    # =========================================================================
    # UBO Fields
    # =========================================================================
    ubo_full_name = fields.Char(string='UBO Full Name')
    ubo_gender = fields.Selection(
        [('male', 'Male'), ('female', 'Female'), ('other', 'Other')], string='UBO Gender'
    )
    ubo_nationality = fields.Char(string='UBO Nationality')
    ubo_date_of_birth = fields.Date(string='UBO Date of Birth')
    ubo_place_of_birth = fields.Char(string='UBO Place of Birth')
    ubo_dual_citizenship = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Citizen of More Than One Country')
    ubo_dual_citizenship_detail = fields.Text(string='Dual Citizenship Details')
    ubo_source_of_income = fields.Text(string='UBO Source of Income')
    ubo_hold_shares_behalf = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='UBO Hold Shares on Behalf of Another')
    ubo_high_risk_jurisdiction = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='UBO High-Risk Jurisdiction')
    ubo_home_country_address = fields.Text(string='UBO Home Country Address')
    ubo_uae_address = fields.Text(string='UBO UAE Address')
    ubo_mobile = fields.Char(string='UBO Mobile Number')
    ubo_email = fields.Char(string='UBO Email ID')
    ubo_high_net_worth = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='High Net Worth Individual (>=USD 15m)')
    ubo_bank_name = fields.Char(string='Bank Name')
    ubo_bank_branch_address = fields.Text(string='Bank Branch Address')
    ubo_iban = fields.Char(string='IBAN / Account Number')

    # =========================================================================
    # One2many Lines
    # =========================================================================
    director_line_ids = fields.One2many('aml.request.director', 'request_id', string='Directors / Managers')
    director_declaration_date = fields.Date(string='Directors Register – As of Date')
    director_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_director_attachments',
        string='Director / Manager Documents',
    )

    shareholder_line_ids = fields.One2many('aml.request.shareholder', 'request_id', string='Shareholders')
    shareholder_declaration_date = fields.Date(string='Shareholder Register – As of Date')
    shareholder_attachment_ids = fields.Many2many(
        'ir.attachment',
        compute='_compute_shareholder_attachments',
        string='Shareholder Documents',
    )

    document_line_ids = fields.One2many('aml.request.document', 'request_id', string='PI Documents')
    hit_document_ids = fields.One2many('aml.hit.document', 'request_id', string='HIT Document Requests')

    # =========================================================================
    # Group expand – show all pipeline stages even when empty
    # =========================================================================
    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _val in self._fields['state'].selection if key != 'draft']

    # =========================================================================
    # Computed
    # =========================================================================
    def _compute_director_attachments(self):
        Attachment = self.env['ir.attachment']
        for rec in self:
            rec.director_attachment_ids = Attachment.search([
                ('res_model', '=', 'aml.request'),
                ('res_id', '=', rec.id),
                ('name', '=like', 'Director %'),
            ])

    def _compute_shareholder_attachments(self):
        Attachment = self.env['ir.attachment']
        for rec in self:
            rec.shareholder_attachment_ids = Attachment.search([
                ('res_model', '=', 'aml.request'),
                ('res_id', '=', rec.id),
                ('name', '=like', 'Shareholder %'),
            ])

    def _compute_user_flags(self):
        is_mgr = self.env.user.has_group('aml_automation_extended_rk.group_aml_manager')
        is_usr = self.env.user.has_group('aml_automation_extended_rk.group_aml_user')
        for rec in self:
            rec.is_aml_manager = is_mgr
            rec.is_aml_user = is_usr

    def _compute_access_url(self):
        for record in self:
            record.access_url = '/aml/form/%s' % (record.access_token or '')

    # =========================================================================
    # =========================================================================
    # Mail Helper
    # =========================================================================
    def _get_mail_from(self):
        """Return a valid sender address for mail.mail.create()."""
        params = self.env['ir.config_parameter'].sudo()
        catchall_domain = params.get_param('mail.catchall.domain')
        default_from = params.get_param('mail.default.from')
        if default_from and catchall_domain:
            return '%s@%s' % (default_from, catchall_domain)
        company = self.company_id or self.env.company
        return company.email or self.env.user.email or ''

    # KYC Email (Python-generated – avoids Odoo 18 template rendering issues)
    # =========================================================================
    def _send_kyc_form_email(self):
        """Build and send the branded KYC form email directly from Python."""
        self.ensure_one()
        partner = self.partner_id
        if not partner.email:
            return

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        self._portal_ensure_token()
        form_url = '%s/aml/form/%s' % (base_url, self.access_token)

        kyc_label = 'Entity' if self.kyc_type == 'entity' else 'Individual'
        order_name = self.sale_order_id.name or ''
        company = self.company_id or self.env.company
        logo_url = '%s/web/image/res.company/%s/logo' % (base_url, company.id)

        body_html = """
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%%"
       style="background:#f4f6fb;padding:24px 0;font-family:Arial,Helvetica,sans-serif;">
  <tr><td align="center">

  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="620"
         style="background:#ffffff;border-radius:10px;border:1px solid #dde3f0;">

    <!-- Header -->
    <tr>
      <td bgcolor="#1a237e" style="padding:32px 40px;text-align:center;border-radius:10px 10px 0 0;">
        <img src="%(logo_url)s" alt="%(company_name)s"
             style="max-height:60px;max-width:180px;display:block;margin:0 auto 14px;"
             border="0"/>
        <h1 style="color:#ffffff;margin:0;font-family:Arial,sans-serif;font-size:20px;font-weight:700;">
          KYC / AML Form – %(company_name)s
        </h1>
        <p style="color:#c5cae9;margin:6px 0 0;font-family:Arial,sans-serif;font-size:13px;">
          UAE AML/CFT Compliance
        </p>
      </td>
    </tr>

    <!-- Body -->
    <tr>
      <td style="padding:32px 40px;background:#ffffff;">
        <p style="color:#1c2340;font-family:Arial,sans-serif;font-size:15px;margin:0 0 18px;">
          Dear <strong>%(partner_name)s</strong>,
        </p>
        <p style="color:#555555;font-family:Arial,sans-serif;font-size:14px;line-height:1.75;margin:0 0 14px;">
          As part of our regulatory obligations under UAE AML/CFT requirements applicable to
          <strong>DNFBPs</strong>, we are required to obtain and verify your customer due diligence
          (KYC) information before commencement of the engagement.
        </p>
        <p style="color:#555555;font-family:Arial,sans-serif;font-size:14px;line-height:1.75;margin:0 0 28px;">
          Please click the button below to securely complete your KYC form.
          The link is <strong>unique to your account</strong> and will expire once submitted.
        </p>

        <!-- CTA Button (VML for Outlook + HTML fallback) -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%%">
          <tr>
            <td align="center" style="padding:20px 0 28px;">
              <!--[if mso]>
              <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml"
                           xmlns:w="urn:schemas-microsoft-com:office:word"
                           href="%(form_url)s"
                           style="height:50px;v-text-anchor:middle;width:240px;"
                           arcsize="10%%" fillcolor="#1a237e" strokecolor="#1a237e">
                <w:anchorlock/>
                <center style="color:#ffffff;font-family:Arial,sans-serif;font-size:15px;font-weight:700;">
                  Complete KYC Form
                </center>
              </v:roundrect>
              <![endif]-->
              <!--[if !mso]><!-->
              <a href="%(form_url)s"
                 style="background-color:#1a237e;color:#ffffff;font-family:Arial,sans-serif;
                        font-size:15px;font-weight:700;padding:14px 36px;text-decoration:none;
                        border-radius:8px;display:inline-block;mso-padding-alt:0;">
                Complete KYC Form
              </a>
              <!--<![endif]-->
            </td>
          </tr>
        </table>

        <!-- Reference box -->
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%%"
               style="background:#f4f6fb;border-left:4px solid #1a237e;border-radius:0 6px 6px 0;margin:0 0 20px;">
          <tr>
            <td style="padding:14px 18px;font-family:Arial,sans-serif;font-size:13px;color:#555555;line-height:1.6;">
              <strong>Reference:</strong> %(order_name)s &nbsp;&nbsp;|&nbsp;&nbsp;
              <strong>KYC Type:</strong> %(kyc_label)s
            </td>
          </tr>
        </table>

        <p style="color:#888888;font-family:Arial,sans-serif;font-size:13px;line-height:1.6;
                  border-top:1px solid #dde3f0;padding-top:18px;margin:0 0 14px;">
          If the button above does not work, copy and paste this link into your browser:
        </p>
        <p style="margin:0 0 18px;">
          <a href="%(form_url)s"
             style="color:#1565c0;font-family:Arial,sans-serif;font-size:13px;word-break:break-all;">
            %(form_url)s
          </a>
        </p>
        <p style="color:#888888;font-family:Arial,sans-serif;font-size:13px;margin:0;">
          If you have any questions, please contact our AML team.
        </p>
      </td>
    </tr>

    <!-- Footer -->
    <tr>
      <td bgcolor="#f4f6fb"
          style="padding:16px 40px;text-align:center;border-top:1px solid #dde3f0;border-radius:0 0 10px 10px;">
        <p style="color:#999999;font-family:Arial,sans-serif;font-size:12px;margin:0;">
          %(company_name)s &nbsp;|&nbsp; UAE AML Compliance Team
        </p>
      </td>
    </tr>

  </table>

  </td></tr>
</table>
        """ % {
            'partner_name': partner.name,
            'form_url': form_url,
            'order_name': order_name,
            'kyc_label': kyc_label,
            'company_name': company.name,
            'logo_url': logo_url,
        }

        self.env['mail.mail'].sudo().create({
            'subject': 'Action Required: Complete Your KYC / AML Form – %s' % (order_name or self.name),
            'body_html': body_html,
            'email_from': self._get_mail_from(),
            'email_to': partner.email,
            'author_id': self.env.user.partner_id.id,
            'model': 'aml.request',
            'res_id': self.id,
        }).send()

        self.message_post(body=_("KYC form link sent to %s (%s).") % (partner.name, partner.email))

    def action_resend_kyc_email(self):
        """Resend the KYC form email to the client (available in draft and new states)."""
        self.ensure_one()
        if not self.partner_id.email:
            raise UserError(_("The client does not have an email address on file."))
        if self.state not in ('draft', 'new'):
            raise UserError(_("The KYC form can only be resent while the request is in Draft or New state."))
        # Reset token so the link is fresh (optional – only if state is still draft)
        if self.state == 'draft':
            self._portal_ensure_token()
        self._send_kyc_form_email()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Email Sent"),
                'message': _("KYC form link resent to %s.") % self.partner_id.email,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
        }

    # =========================================================================
    # Portal fields whitelist per page (security – only these fields written from portal)
    # =========================================================================
    _PORTAL_FIELDS = {
        'kyc_entity': [
            'ent_entity_name', 'ent_legal_type', 'ent_trading_name',
            'ent_date_of_incorporation', 'ent_place_of_incorporation',
            'ent_registration_authority', 'ent_license_number', 'ent_license_expiry',
            'ent_registered_address', 'ent_business_address', 'ent_industry_type',
            'ent_nature_of_business', 'ent_source_of_wealth', 'ent_ownership_complexity',
            'ent_countries_commercial', 'ent_high_risk_jurisdiction',
            'ent_channel_cash', 'ent_channel_wire', 'ent_channel_cheque',
            'ent_channel_credit', 'ent_channel_crypto', 'ent_channel_debit',
            'ent_cash_less_50k', 'ent_cash_more_50k', 'ent_cash_na',
            'ent_top5_suppliers', 'ent_top5_customers',
            'ent_contact_name', 'ent_contact_designation', 'ent_contact_email', 'ent_contact_mobile',
            'ent_manager_name', 'ent_parent_company_name', 'ent_parent_company_address',
            'ent_international_sanctions',
            'ent_pep_shareholder', 'ent_pep_director', 'ent_pep_owner',
            'ent_pep_local_sponsor', 'ent_pep_key_management', 'ent_pep_officer', 'ent_pep_agent',
        ],
        'kyc_individual': [
            'ind_full_name', 'ind_gender', 'ind_nationality', 'ind_date_of_birth',
            'ind_place_of_birth', 'ind_id_type', 'ind_id_type_other', 'ind_id_number',
            'ind_issuing_country', 'ind_valid_until', 'ind_permanent_address',
            'ind_uae_address', 'ind_city', 'ind_country', 'ind_mobile', 'ind_email',
            'ind_proof_address_type', 'ind_proof_address_other', 'ind_document_date',
            'ind_emirates_id_attached', 'ind_passport_attached',
            'ind_proof_address_attached', 'ind_other_id_attached',
            'ind_verified_portal', 'ind_verified_physically', 'ind_video_kyc',
            'ind_purpose_of_relationship', 'ind_purpose_of_relationship_other', 'ind_expected_transactions',
            'ind_monthly_turnover', 'ind_source_of_funds', 'ind_hold_shares_behalf',
            'ind_high_risk_jurisdiction', 'ind_anticipated_origin',
            'ind_dual_citizenship', 'ind_dual_citizenship_detail', 'ind_high_net_worth',
            'ind_bank_name', 'ind_bank_branch_address', 'ind_iban',
        ],
        'ubo': [
            'ubo_full_name', 'ubo_gender', 'ubo_nationality', 'ubo_date_of_birth',
            'ubo_place_of_birth', 'ubo_dual_citizenship', 'ubo_dual_citizenship_detail',
            'ubo_source_of_income', 'ubo_hold_shares_behalf', 'ubo_high_risk_jurisdiction',
            'ubo_home_country_address', 'ubo_uae_address', 'ubo_mobile', 'ubo_email',
            'ubo_high_net_worth', 'ubo_bank_name', 'ubo_bank_branch_address', 'ubo_iban',
        ],
        'directors': ['director_declaration_date'],
        'shareholders': ['shareholder_declaration_date'],
        'sign': ['signatory_name', 'accept_declaration'],
    }

    def get_portal_fields_for_page(self, page):
        return self._PORTAL_FIELDS.get(page, [])

    # =========================================================================
    # Manager Actions
    # =========================================================================
    def action_accept(self):
        self.ensure_one()
        if not self.env.user.has_group('aml_automation_extended_rk.group_aml_manager'):
            raise UserError(_("Only AML Managers can accept requests."))
        if self.state != 'new':
            raise UserError(_("Only new requests can be accepted."))

        aml_users = self.env['res.users'].search([
            ('groups_id', 'in', [self.env.ref('aml_automation_extended_rk.group_aml_user').id]),
            ('active', '=', True),
        ], limit=1)

        self.write({
            'state': 'accepted',
            'aml_user_id': aml_users.id if aml_users else False,
        })
        self.message_post(body=_("Request accepted. Assigned to AML pipeline."))
        self._notify_aml_users_accepted()

    def action_bypass(self):
        self.ensure_one()
        if not self.env.user.has_group('aml_automation_extended_rk.group_aml_manager'):
            raise UserError(_("Only AML Managers can bypass requests."))
        if self.state != 'new':
            raise UserError(_("Only new requests can be bypassed."))
        self.write({'state': 'bypassed'})
        self.message_post(body=_("Request bypassed. No AML check required."))
        self._notify_management_and_salesperson(
            subject=_("AML Request %s – Bypassed (No AML Required)") % self.name,
            body=_(
                "<p>AML Request <strong>%s</strong> for client <strong>%s</strong> "
                "has been <strong>bypassed</strong>. No AML check is required.</p>"
                "<p>Sale Order: %s</p>"
            ) % (self.name, self.partner_id.name, self.sale_order_id.name or '-'),
        )

    def action_cancel(self):
        self.ensure_one()
        if not self.env.user.has_group('aml_automation_extended_rk.group_aml_manager'):
            raise UserError(_("Only AML Managers can cancel requests."))
        if self.state != 'new':
            raise UserError(_("Only new requests can be cancelled."))
        self.write({'state': 'cancelled'})
        self.message_post(body=_("Request cancelled."))
        self._notify_management_and_salesperson(
            subject=_("AML Request %s – Cancelled") % self.name,
            body=_(
                "<p>AML Request <strong>%s</strong> for client <strong>%s</strong> "
                "has been <strong>cancelled</strong>.</p>"
                "<p>Sale Order: %s</p>"
            ) % (self.name, self.partner_id.name, self.sale_order_id.name or '-'),
        )

    # =========================================================================
    # AML User Actions
    # =========================================================================
    def action_start_progress(self):
        self.ensure_one()
        if self.state != 'accepted':
            raise UserError(_("Only accepted requests can be started."))
        self.write({
            'state': 'in_progress',
            'start_datetime': fields.Datetime.now(),
        })
        self.message_post(body=_("AML investigation started by %s.") % self.env.user.name)

    def action_no_hit(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_("Request must be In Progress to mark No HIT."))
        self.write({'state': 'no_hit'})
        self.message_post(body=_("No HIT Detected. Request marked as completed."))
        self._notify_aml_managers_and_management(
            subject=_("AML Request %s – No HIT Detected") % self.name,
            body=_(
                "<p>AML Request <strong>%s</strong> for client <strong>%s</strong> "
                "has been completed with <strong>No HIT Detected</strong>.</p>"
            ) % (self.name, self.partner_id.name),
        )

    def action_hit_detected(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_("Request must be In Progress to mark HIT Detected."))
        self.write({'state': 'hit_detected'})
        self.message_post(body=_("HIT Detected! Opening wizard to request additional documents."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Request Additional Documents'),
            'res_model': 'aml.hit.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_additional_documents(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_("Request must be In Progress to request additional documents."))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Request Additional Documents'),
            'res_model': 'aml.additional.docs.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_approve(self):
        self.ensure_one()
        if self.state != 'additional_info':
            raise UserError(_("Can only approve after additional info is received."))
        self.write({'state': 'approved'})
        self.message_post(body=_("AML Request approved."))
        self._notify_aml_managers_and_management(
            subject=_("AML Request %s – Approved") % self.name,
            body=_(
                "<p>AML Request <strong>%s</strong> for client <strong>%s</strong> "
                "has been <strong>approved</strong>.</p>"
            ) % (self.name, self.partner_id.name),
        )

    def action_reject(self):
        self.ensure_one()
        if self.state != 'additional_info':
            raise UserError(_("Can only reject after additional info is received."))
        self.write({'state': 'rejected'})
        self.message_post(body=_("AML Request rejected."))
        self._notify_aml_managers_and_management(
            subject=_("AML Request %s – Rejected") % self.name,
            body=_(
                "<p>AML Request <strong>%s</strong> for client <strong>%s</strong> "
                "has been <strong>rejected</strong>. The pipeline record is now closed.</p>"
            ) % (self.name, self.partner_id.name),
        )

    # =========================================================================
    # Notification Helpers
    # =========================================================================
    def _notify_management_and_salesperson(self, subject, body):
        management = self.company_id.approver_user_id
        salesperson = self.sale_order_id.user_id if self.sale_order_id else False
        recipients = set()
        if management and management.email:
            recipients.add(management.email)
        if salesperson and salesperson.email:
            recipients.add(salesperson.email)
        full_body = "<p>Dear Team,</p>%s<p>Regards,<br/>AML System</p>" % body
        email_from = self._get_mail_from()
        for email in recipients:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': full_body,
                'email_from': email_from,
                'email_to': email,
                'author_id': self.env.user.partner_id.id,
            }).send()

    def _notify_aml_managers_and_management(self, subject, body):
        manager_group = self.env.ref('aml_automation_extended_rk.group_aml_manager')
        aml_managers = self.env['res.users'].search([
            ('groups_id', 'in', [manager_group.id]), ('active', '=', True)
        ])
        management = self.company_id.approver_user_id
        recipients = set()
        for u in aml_managers:
            if u.email:
                recipients.add(u.email)
        if management and management.email:
            recipients.add(management.email)
        full_body = "<p>Dear Team,</p>%s<p>Regards,<br/>AML System</p>" % body
        email_from = self._get_mail_from()
        for email in recipients:
            self.env['mail.mail'].sudo().create({
                'subject': subject,
                'body_html': full_body,
                'email_from': email_from,
                'email_to': email,
                'author_id': self.env.user.partner_id.id,
            }).send()

    def _notify_aml_users_accepted(self):
        user_group = self.env.ref('aml_automation_extended_rk.group_aml_user')
        aml_users = self.env['res.users'].search([
            ('groups_id', 'in', [user_group.id]), ('active', '=', True)
        ])
        body_html = _(
            "<p>Dear AML Officer,</p>"
            "<p>A new AML request <strong>%s</strong> for client <strong>%s</strong> "
            "has been accepted and is now in your pipeline.</p>"
            "<p>KYC Type: %s | Deadline: %s</p>"
            "<p>Please review and take action.</p>"
        ) % (
            self.name, self.partner_id.name,
            dict(self._fields['kyc_type'].selection).get(self.kyc_type or '', ''),
            self.deadline,
        )
        email_from = self._get_mail_from()
        for user in aml_users:
            if user.email:
                self.env['mail.mail'].sudo().create({
                    'subject': _("New AML Request Assigned: %s") % self.name,
                    'body_html': body_html,
                    'email_from': email_from,
                    'email_to': user.email,
                    'author_id': self.env.user.partner_id.id,
                }).send()

    def _notify_aml_managers_new_request(self):
        manager_group = self.env.ref('aml_automation_extended_rk.group_aml_manager')
        aml_managers = self.env['res.users'].search([
            ('groups_id', 'in', [manager_group.id]), ('active', '=', True)
        ])
        body_html = _(
            "<p>Dear AML Manager,</p>"
            "<p>A new AML request <strong>%s</strong> has been submitted by client "
            "<strong>%s</strong> via the KYC web form.</p>"
            "<p>KYC Type: %s | Deadline: %s</p>"
            "<p>Please log in to review and take action.</p>"
            "<p>Regards,<br/>AML System</p>"
        ) % (
            self.name, self.partner_id.name,
            dict(self._fields['kyc_type'].selection).get(self.kyc_type or '', ''),
            self.deadline,
        )
        email_from = self._get_mail_from()
        for manager in aml_managers:
            if manager.email:
                self.env['mail.mail'].sudo().create({
                    'subject': _("New AML Request: %s") % self.name,
                    'body_html': body_html,
                    'email_from': email_from,
                    'email_to': manager.email,
                    'author_id': self.env.user.partner_id.id,
                }).send()

    # =========================================================================
    # Scheduled / Cron Actions
    # =========================================================================
    @api.model
    def _cron_pending_to_aml_manager(self):
        """Every 2 days: send pending AML records (>1 day old) to AML managers."""
        now = fields.Datetime.now()
        cutoff = now - timedelta(days=1)
        pending = self.search([
            ('state', 'in', ('new', 'accepted', 'in_progress', 'hit_detected', 'additional_info')),
            ('write_date', '<', cutoff),
        ])
        if not pending:
            return
        manager_group = self.env.ref('aml_automation_extended_rk.group_aml_manager')
        aml_managers = self.env['res.users'].search([
            ('groups_id', 'in', [manager_group.id]), ('active', '=', True)
        ])
        state_labels = dict(self._fields['state'].selection)
        rows = ''.join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                r.name, r.partner_id.name,
                dict(self._fields['kyc_type'].selection).get(r.kyc_type or '', ''),
                state_labels.get(r.state, r.state),
                r.deadline or 'N/A',
            ) for r in pending
        )
        body = (
            "<p>Dear AML Manager,</p>"
            "<p>The following AML requests have been pending for more than 1 day:</p>"
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%%'>"
            "<thead><tr><th>AML ID</th><th>Client</th><th>KYC Type</th><th>Status</th><th>Deadline</th></tr></thead>"
            "<tbody>%s</tbody></table>"
            "<p>Regards,<br/>AML System</p>"
        ) % rows
        email_from = self._get_mail_from()
        for mgr in aml_managers:
            if mgr.email:
                self.env['mail.mail'].sudo().create({
                    'subject': "Pending AML Requests Summary",
                    'body_html': body,
                    'email_from': email_from,
                    'email_to': mgr.email,
                    'author_id': self.env.user.partner_id.id,
                }).send()

    @api.model
    def _cron_pending_to_management(self):
        """Weekly: send pending AML list to management."""
        now = fields.Datetime.now()
        cutoff = now - timedelta(days=1)
        pending = self.search([
            ('state', 'in', ('new', 'accepted', 'in_progress', 'hit_detected', 'additional_info')),
            ('write_date', '<', cutoff),
        ])
        if not pending:
            return
        management_users = self.env['res.company'].search([]).mapped('approver_user_id').filtered(
            lambda u: u and u.email
        )
        state_labels = dict(self._fields['state'].selection)
        rows = ''.join(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                r.name, r.partner_id.name,
                dict(self._fields['kyc_type'].selection).get(r.kyc_type or '', ''),
                state_labels.get(r.state, r.state),
                r.deadline or 'N/A',
            ) for r in pending
        )
        body = (
            "<p>Dear Management,</p>"
            "<p>Weekly AML Request Status Summary — Pending requests:</p>"
            "<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse;width:100%%'>"
            "<thead><tr><th>AML ID</th><th>Client</th><th>KYC Type</th><th>Status</th><th>Deadline</th></tr></thead>"
            "<tbody>%s</tbody></table>"
            "<p>Regards,<br/>AML System</p>"
        ) % rows
        email_from = self._get_mail_from()
        for user in management_users:
            self.env['mail.mail'].sudo().create({
                'subject': "Weekly AML Requests Summary",
                'body_html': body,
                'email_from': email_from,
                'email_to': user.email,
                'author_id': self.env.user.partner_id.id,
            }).send()

    def get_logo_white_jpeg(self):
        """Composite company logo onto a white background and return as base64 JPEG.
        JPEG has no alpha channel so transparent areas can never render as black.
        Returns False if Pillow is unavailable so the caller can fall back."""
        company = self.company_id or self.env.company
        if not company.logo:
            return False
        try:
            from PIL import Image as PILImage
            logo_b64 = company.logo
            if isinstance(logo_b64, bytes):
                logo_b64 = logo_b64.decode('utf-8')
            raw = base64.b64decode(logo_b64)
            img = PILImage.open(BytesIO(raw)).convert('RGBA')
            bg = PILImage.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            out = BytesIO()
            bg.save(out, format='JPEG', quality=95)
            return base64.b64encode(out.getvalue())
        except Exception:
            return False
