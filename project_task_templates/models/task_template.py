from odoo import api, fields, models

class ProjectTask(models.Model):
    _inherit = 'project.task'

    template_type = fields.Selection([
        ('asm', 'Accounting Summary Memorandum (ASM)'),
        ('audit', 'Audit Summary Memorandum')
    ], string='Template Type')

    # One2many fields for separate templates
    asm_summary_id = fields.One2many('task.asm.summary', 'task_id', string='Accounting ASM')
    audit_summary_id = fields.One2many('task.audit.summary', 'task_id', string='Audit ASM')

    @api.onchange('template_type')
    def _onchange_template_type(self):
        if self.template_type == 'asm':
            self.audit_summary_id = [(5, 0, 0)]
        elif self.template_type == 'audit':
            self.asm_summary_id = [(5, 0, 0)]


# ------------------------
# Accounting ASM Model
# ------------------------
class TaskAsmSummary(models.Model):
    _name = 'task.asm.summary'
    _description = 'Accounting Summary Memorandum'

    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade')

    # Client Info
    client_id = fields.Many2one('res.partner', string='Client', required=True)
    period = fields.Char('Period', required=True)
    prepared_by_id = fields.Many2one('res.users', string='Prepared By')
    reviewed_by_id = fields.Many2one('res.users', string='Reviewed By')
    se_code_id = fields.Many2one('sale.order', string='SE Code')

    # Executive Snapshot
    revenue_month = fields.Float('Revenue (This Month)')
    expenses_month = fields.Float('Expenses (This Month)')
    net_profit_month = fields.Float('Net Profit (This Month)')
    revenue_ytd = fields.Float('Revenue (YTD)')
    expenses_ytd = fields.Float('Expenses (YTD)')
    net_profit_ytd = fields.Float('Net Profit (YTD)')
    receivables = fields.Float('Receivables (Total)')
    payables = fields.Float('Payables (Total)')
    cash_bank = fields.Float('Cash / Bank')
    vat_net = fields.Float('VAT (Net for month)')
    ct_provision = fields.Float('CT Provision (YTD)')
    overall_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Overall Risk')

    # Client Profile
    business_activity = fields.Char('Business Activity')
    employees = fields.Integer('Employees')
    key_trading_partners = fields.Char('Key Trading Partners/Markets')
    compliance = fields.Char('Compliance')
    entity_type = fields.Char('Entity Type')
    risk_factors = fields.Char('Risk Factors')
    annual_turnover = fields.Char('Annual Turnover')
    overall_client_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Overall Client Risk')

    # Compliance
    aml_status = fields.Char('AML Status')
    upcoming_deadlines = fields.Char('Upcoming Deadlines')
    vat_status = fields.Char('VAT Status')
    risk_linkage = fields.Char('Risk Linkage')
    ct_status = fields.Char('Corporate Tax (CT) Status')
    audit_required = fields.Char('Audit Required')

    # Risk Assessment
    aml_kyc_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='AML / KYC')
    financial_ar_ap_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Financial (AR/AP)')
    compliance_vat_ct_tp_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Compliance (VAT/CT/TP)')
    engagement_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Engagement')
    collections_fees_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Collections / Fees')
    free_zone_ct_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Free Zone CT Assessment')
    outsourcing_cigas_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Outsourcing of CIGAs')
    total_score = fields.Integer('Total Score')
    overall_risk_assessment = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Overall Risk')

    #AML/Compliance Monitoring
    aml_ids = fields.One2many('task.asm.aml', 'asm_id', string='AML / Compliance Monitoring')

    #Receivables & Payables Ageing
    apar_ids = fields.One2many('task.asm.apar', 'asm_id', string='Receivables & Payables Ageing')
    apar_key_concern = fields.Char('Key Concern')
    issue_ids = fields.One2many('task.asm.issue', 'asm_id', string='Issues & Risk Rating')
    file_review_ids = fields.One2many('task.asm.filereview', 'asm_id', string='File Review Status (QC)')
    fr_qc_score = fields.Char('QC Score')
    fr_qc_status = fields.Char('QC Status')
    engagement_fee_ids = fields.One2many('task.asm.engagement.fee', 'asm_id', string='Engagement Fees & Billing')

    @api.onchange('se_code_id')
    def _onchange_se_code_id(self):
        """When SE Code changes, fetch its invoices properly."""
        for rec in self:
            rec.engagement_fee_ids = [(5, 0, 0)]
            if not rec.se_code_id:
                continue

            sale = rec.se_code_id
            engagement_value = sale.amount_total or 0.0

            # Correct way to fetch invoices linked to this sale order
            invoices = self.env['account.move'].search([
                ('invoice_origin', 'ilike', sale.name),
                ('move_type', '=', 'out_invoice')
            ])

            if not invoices and hasattr(sale, 'invoice_ids'):
                invoices = sale.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')

            fee_lines = []
            for inv in invoices:
                paid = inv.amount_total - inv.amount_residual
                outstanding = inv.amount_residual
                percent_raised = (inv.amount_total / engagement_value * 100) if engagement_value else 0.0
                billing_terms = (
                    inv.invoice_payment_term_id.name
                    or inv.invoice_origin
                    or inv.narration
                    or 'N/A'
                )

                fee_lines.append((0, 0, {
                    'invoice_id': inv.id,
                    'invoice_state': inv.state,
                    'engagement_fee': engagement_value,
                    'invoice_value': inv.amount_total,
                    'collected': paid,
                    'outstanding': outstanding,
                    'percent_collected': percent_raised,
                    'billing_terms': billing_terms,
                }))

            rec.engagement_fee_ids = fee_lines


class TaskAsmAml(models.Model):
    _name = 'task.asm.aml'
    _description = 'ASM AML / Compliance Monitoring'

    asm_id = fields.Many2one('task.asm.summary', string='ASM', ondelete='cascade')
    aml_item = fields.Char('AML Item')
    aml_item_status = fields.Char('Status')
    aml_risk = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Risk')
    aml_action_required = fields.Char('Action Required')
    aml_priority = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Priority')
    aml_owner = fields.Char('Owner')

class TaskAsmApar(models.Model):
    _name = 'task.asm.apar'
    _description = 'Receivables & Payables Ageing'

    asm_id = fields.Many2one('task.asm.summary', string='ASM', ondelete='cascade')
    category = fields.Char('Category')
    days30 = fields.Integer('<30 days')
    days30_60 = fields.Integer('31-60')
    days61_90 = fields.Integer('31-90')
    days90 = fields.Integer('>90')
    daystotal = fields.Integer('Total')

class TaskAsmIssue(models.Model):
    _name = 'task.asm.issue'
    _description = 'ASM Issues & Risk Rating'

    asm_id = fields.Many2one('task.asm.summary', string='ASM', ondelete='cascade')
    issue = fields.Char('Issue')
    impact = fields.Char('Impact')
    likelihood = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Likelihood')
    risk_level = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Risk Level')
    owner = fields.Char('Owner')
    priority = fields.Selection([('low','Low'),('medium','Medium'),('high','High')], string='Priority')

class TaskAsmFileReview(models.Model):
    _name = 'task.asm.filereview'
    _description = 'ASM File Review Status'

    asm_id = fields.Many2one('task.asm.summary', string='ASM', ondelete='cascade')
    area = fields.Char('Area')
    status = fields.Selection([('done','Done'),('pending','Pending'),('na','N/A')], string='Status')
    reviewer_notes = fields.Text('Reviewer Notes')
    evidence_link = fields.Char('Evidence / Link')
    date_checked = fields.Date('Date Checked')
    owner = fields.Char('Owner')

class TaskAsmEngagementFee(models.Model):
    _name = 'task.asm.engagement.fee'
    _description = 'ASM Engagement Fees & Billing Status'

    asm_id = fields.Many2one('task.asm.summary', string='ASM', ondelete='cascade')
    invoice_id = fields.Many2one('account.move', string='Invoice', readonly=True)
    invoice_state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancel', 'Cancelled'),
    ], string='State', readonly=True)

    engagement_fee = fields.Float('Engagement Value', readonly=True)
    invoice_value = fields.Float('Invoice Value', readonly=True)
    collected = fields.Float('Paid Value', readonly=True)
    outstanding = fields.Float('Outstanding', readonly=True)
    percent_collected = fields.Float('% of Engagement Raised', readonly=True)
    billing_terms = fields.Char('Billing Terms / Description', readonly=True)


# ------------------------
# Audit ASM Model
# ------------------------
class TaskAuditSummary(models.Model):
    _name = 'task.audit.summary'
    _description = 'Audit Summary Memorandum'

    task_id = fields.Many2one('project.task', string='Task', ondelete='cascade')

    # Client Info
    entity_name = fields.Char('Name of the Entity')
    authority = fields.Char('Authority')
    business_activity = fields.Char('Business Activity as per license')
    odoo_se = fields.Char('ODOO SE')
    fees = fields.Float('Fees (AED/USD)')
    auditor_code = fields.Char('Auditor Code')
    year_ended = fields.Date('Year/Period Ended')
    submitted_on = fields.Date('Submitted On')
    deliverables = fields.Text('Deliverables')

    # Invoicing
    advance_fee = fields.Float('Advance Fee Amount')
    advance_invoice_no = fields.Char('Advance Invoice No.')
    advance_invoice_date = fields.Date('Advance Invoice Date')
    balance_fee = fields.Float('Balance Fee Amount')
    balance_invoice_no = fields.Char('Balance Invoice No.')
    balance_invoice_date = fields.Date('Balance Invoice Date')

    # Engagement Team Members
    partner = fields.Char('Partner')
    manager = fields.Char('Manager')
    senior_auditor = fields.Char('Senior Auditor')
    auditor = fields.Char('Auditor')
    audit_trainee = fields.Char('Audit Trainee')
    eqcr = fields.Char('EQCR (if applicable)')
    total_hours = fields.Float('Total Hours')

    # Audit Planning, Execution, Completion
    audit_planning = fields.Text('Audit Planning, Execution and Completion')
    aml_kyc = fields.Text('AML & KYC')
    materiality = fields.Text('Materiality')
    significant_issues = fields.Text('Significant Accounting and Audit Issues')
    key_audit_matters = fields.Text('Summary of Key Audit Matters')
    going_concern = fields.Text('Going Concern')
    post_reporting_events = fields.Text('Events after the reporting period')
    review_and_approval = fields.Text('Review and Approval')
