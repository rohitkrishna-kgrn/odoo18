from odoo import models, fields, api


class AmlRequestDirector(models.Model):
    _name = 'aml.request.director'
    _description = 'AML Request Director / Manager Line'
    _order = 'sequence, id'

    request_id = fields.Many2one('aml.request', string='AML Request', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sr. No.', default=10)
    full_name = fields.Char(string='Full Name', required=True)
    position = fields.Char(string='Position (Director / Manager / Secretary)')
    nationality = fields.Char(string='Nationality')
    id_passport_no = fields.Char(string='ID / Passport No.')
    appointment_date = fields.Date(string='Appointment Date')
    resignation_date = fields.Date(string='Resignation / Removal Date')
    status = fields.Selection([
        ('active', 'Active'),
        ('resigned', 'Resigned'),
    ], string='Status', default='active')


class AmlRequestShareholder(models.Model):
    _name = 'aml.request.shareholder'
    _description = 'AML Request Shareholder Line'
    _order = 'sequence, id'

    request_id = fields.Many2one('aml.request', string='AML Request', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sr. No.', default=10)
    shareholder_name = fields.Char(string='Shareholder Name', required=True)
    nationality = fields.Char(string='Nationality')
    shareholder_type = fields.Selection([
        ('individual', 'Individual'),
        ('corporate', 'Corporate'),
    ], string='Shareholder Type')
    passport_no = fields.Char(string='Passport No.')
    share_class = fields.Selection([
        ('ordinary', 'Ordinary'),
        ('preference', 'Preference'),
    ], string='Share Class')
    num_shares = fields.Integer(string='No. of Shares Held')
    percentage_holding = fields.Float(string='% Holding', digits=(5, 2))
    date_of_entry = fields.Date(string='Date of Entry')


class AmlRequestDocument(models.Model):
    _name = 'aml.request.document'
    _description = 'AML Request Preliminary Information Document'
    _order = 'sequence'

    PI_DOCS = [
        # Entity documents
        ('trade_license', 'Latest copy of trade license'),
        ('branch_licenses', 'Latest copy of all branch licenses (if any)'),
        ('cert_incorporation', 'Certificate of incorporation'),
        ('vat_corp_tax', 'UAE VAT & Corporate Tax Registration Certificate'),
        ('moa', 'Memorandum and Articles of Association'),
        ('cert_incumbency', 'Certificate of incumbency / good standing'),
        ('board_resolution', 'Board Resolution authorizing appointment of auditor'),
        ('share_certificates', 'Share certificates'),
        ('org_chart', 'Organizational / Group Chart up to UBO'),
        ('lease_agreement', 'Lease agreement of entity'),
        ('business_profile', 'Business profile / Description of business activities'),
        ('authorized_signatories', 'List of authorized signatories'),
        ('family_book', 'Family book issued by UAE Government (UAE National)'),
        ('residing_together_declaration', 'Declaration – shareholders/managers residing together (if applicable)'),
        ('related_party_licenses', 'License copies of related parties / parent companies (if applicable)'),
        # Individual documents
        ('ind_passport_copy', 'Passport Copy (Front & Back)'),
        ('ind_proof_residence', 'Proof of Residence (Utility Bill / Lease Agreement / Bank Statement)'),
        ('ind_visa', 'Visa'),
        ('ind_emirates_id_doc', 'Emirates ID'),
        ('ind_profile_cv', 'Profile Information / Resume / CV with Photograph'),
    ]

    PI_MANDATORY = {
        # Entity mandatory
        'trade_license', 'vat_corp_tax', 'moa',
        'org_chart', 'lease_agreement',
        'business_profile',
        # Individual mandatory
        'ind_passport_copy', 'ind_proof_residence',
    }

    PI_TOOLTIPS = {
        'authorized_signatories': 'Fill the Excel format provided. Details must match supporting documents.',
        'residing_together_declaration': 'Required only if shareholder stays with family and has no separate proof of residence.',
        'cert_incumbency': 'Any one of certificate of incumbency or good standing certificate.',
    }

    request_id = fields.Many2one('aml.request', string='AML Request', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Seq', default=10)
    doc_key = fields.Selection(PI_DOCS, string='Document Type', required=True)
    doc_name = fields.Char(string='Document Name', compute='_compute_doc_name', store=True)
    is_mandatory = fields.Boolean(string='Mandatory', compute='_compute_mandatory', store=True)
    tooltip = fields.Char(string='Explanation', compute='_compute_tooltip', store=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'aml_doc_attachment_rel', 'doc_id', 'attachment_id',
        string='Uploaded Files',
    )
    is_submitted = fields.Boolean(string='Submitted', default=False)

    @api.depends('doc_key')
    def _compute_doc_name(self):
        doc_map = dict(self.PI_DOCS)
        for rec in self:
            rec.doc_name = doc_map.get(rec.doc_key, '')

    @api.depends('doc_key')
    def _compute_mandatory(self):
        for rec in self:
            rec.is_mandatory = rec.doc_key in self.PI_MANDATORY

    @api.depends('doc_key')
    def _compute_tooltip(self):
        for rec in self:
            rec.tooltip = self.PI_TOOLTIPS.get(rec.doc_key, '')

    def action_download_attachments(self):
        self.ensure_one()
        attachments = self.attachment_ids
        if not attachments:
            return
        if len(attachments) == 1:
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/%s?download=true' % attachments.id,
                'target': 'new',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': 'Files – %s' % self.doc_name,
            'res_model': 'ir.attachment',
            'view_mode': 'list',
            'views': [(self.env.ref('aml_automation_extended_rk.view_aml_attachment_list').id, 'list')],
            'domain': [('id', 'in', attachments.ids)],
            'target': 'new',
            'context': {'create': False, 'delete': False},
        }


class AmlHitDocument(models.Model):
    _name = 'aml.hit.document'
    _description = 'AML HIT – Additional Document Request'
    _order = 'sequence asc, id asc'

    request_id = fields.Many2one('aml.request', string='AML Request', ondelete='cascade', required=True)
    sequence = fields.Integer(default=10)
    document_name = fields.Char(string='Document Requested', required=True)
    attachment_ids = fields.Many2many(
        'ir.attachment',
        'aml_hit_doc_attachment_rel', 'hit_doc_id', 'attachment_id',
        string='Uploaded Files',
    )
    submitted = fields.Boolean(string='Submitted by Client', default=False)
