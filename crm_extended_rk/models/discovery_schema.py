# -*- coding: utf-8 -*-
"""
Single source of truth for every Client Discovery Form.

The same structure drives:
  * the public QWeb form rendering (controllers/main.py -> templates/discovery_form.xml)
  * server-side parsing / validation of the submitted payload
  * the human-readable HTML summary stored in the pipeline record's notebook
  * the PDF export (models/discovery_report.py -> reports/discovery_report.xml)

Field spec keys
---------------
key       : machine key used in the submitted JSON payload
label     : question shown to the client
type      : text | email | phone | number | select | radio | checkbox |
            checkbox_single | textarea | signature
required  : bool
options   : list of str OR list of {'value', 'label'} (for select/radio/checkbox)
help      : sub-text / description shown under the label
placeholder: optional input placeholder
prefill   : optional key into the lead's prefill dict (company_name / contact_name /
            email / phone) used to pre-populate the field from the opportunity
show_if   : optional {'field': <sibling key>, 'contains': [values]} -> conditional
            visibility

Multiple named forms
---------------------
`DISCOVERY_FORMS` maps a `crm.lead.discovery_form_type` selection value to a
form definition: its dropdown label and its list of sections. Every form
shares the same public-form template, PDF layout and email flow; only the
section/field content differs.
"""


def opt(*labels):
    """Build a list of {'value','label'} options where value == label."""
    return [{'value': l, 'label': l} for l in labels]


# ==================================================================
# Shared building blocks reused by every form
# ==================================================================
def contact_section(section_id='S01', extra_fields=None, mobile_required=True):
    """Standard 'who are you' section every discovery form opens with."""
    fields = [
        {'key': 'legalCompanyName', 'label': 'Legal company name', 'type': 'text',
         'required': True, 'prefill': 'company_name',
         'help': 'Full registered legal name of the company'},
    ]
    if extra_fields:
        fields += extra_fields
    fields += [
        {'key': 'primaryContactName', 'label': 'Primary contact name', 'type': 'text',
         'required': True, 'prefill': 'contact_name',
         'help': 'Full name of the main point of contact'},
        {'key': 'primaryContactEmail', 'label': 'Business email', 'type': 'email',
         'required': True, 'prefill': 'email',
         'help': 'Work email address for correspondence'},
        {'key': 'primaryContactMobile', 'label': 'Phone number', 'type': 'phone',
         'required': mobile_required, 'prefill': 'phone',
         'placeholder': '+971 50 000 0000',
         'help': 'Mobile or direct phone with international dial code'},
    ]
    return {
        'id': section_id,
        'title': 'Company & Contact Information',
        'subtitle': "Tell us who you are so we can address the engagement correctly.",
        'fields': fields,
    }


def confirmation_section(section_id):
    """Standard closing section: confirmation checkbox + signature."""
    return {
        'id': section_id,
        'title': 'Submission Confirmation & Signature',
        'subtitle': "Confirm accuracy and sign to authorise the submission.",
        'fields': [
            {'key': 'submissionConfirmed', 'label': 'I confirm the information provided is accurate.',
             'type': 'checkbox_single', 'required': True,
             'help': 'Must be checked to enable submission'},
            {'key': 'signatureData', 'label': 'Signature', 'type': 'signature', 'required': True,
             'help': 'Draw your signature to authorise the submission'},
        ],
    }


YES_NO = opt('Yes', 'No')
YES_NO_NOT_SURE = opt('Yes', 'No', 'Not sure')


# ==================================================================
# 1) eInvoicing — original discovery form
# ==================================================================
# Per-entity sub-form (repeats once per legal entity in scope). All base
# entity fields are mandatory; the conditional S6/S7/S8 selects are
# validated only while visible (see the show_if logic in the front-end).
EINVOICING_ENTITY_FIELDS = [
    {'key': 'entityName', 'label': 'Entity name', 'type': 'text', 'required': True,
     'help': 'Legal name of this entity'},
    {'key': 'erpSystem', 'label': 'ERP / accounting system', 'type': 'text', 'required': True,
     'placeholder': 'e.g. SAP, Oracle, Odoo, QuickBooks, Tally, Zoho',
     'help': 'ERP or accounting software used by this entity'},
    {'key': 'inboundCount', 'label': 'Annual inbound invoice count', 'type': 'number',
     'required': True, 'min': 0, 'help': 'Approx. supplier invoices received per year'},
    {'key': 'outboundCount', 'label': 'Annual outbound invoice count', 'type': 'number',
     'required': True, 'min': 0, 'help': 'Approx. customer invoices issued per year'},
    {'key': 'services', 'label': 'Services required for this entity', 'type': 'checkbox',
     'required': True, 'help': 'Which KGRN service lines are needed for this entity',
     'options': [
         {'value': 'S1', 'label': 'S1 — Readiness Assessment / Gap Analysis'},
         {'value': 'S2', 'label': 'S2 — Data Readiness & Remediation'},
         {'value': 'S3', 'label': 'S3 — Standard Entity Onboarding'},
         {'value': 'S4', 'label': 'S4 — Standard Implementation'},
         {'value': 'S5', 'label': 'S5 — Extended Technical / API Integration'},
         {'value': 'S6', 'label': 'S6 — Annual ASP / Subscription'},
         {'value': 'S7A', 'label': 'S7A — Standard Support'},
         {'value': 'S7B', 'label': 'S7B — Extended Support'},
         {'value': 'S8', 'label': 'S8 — Managed Services'},
     ]},
    {'key': 's6Edition', 'label': 'S6 Platform Edition', 'type': 'select', 'required': True,
     'help': 'Required when S6 is selected', 'show_if': {'field': 'services', 'contains': ['S6']},
     'options': opt(
         'Edition A — Standard Compliance Gateway',
         'Edition B — Assisted Upload & Storage',
         'Edition C — Integrated Operations Platform',
         'Edition D — Enterprise Control Tower')},
    {'key': 's7Tier', 'label': 'Support Tier', 'type': 'select', 'required': True,
     'help': 'Required when S7A or S7B is selected',
     'show_if': {'field': 'services', 'contains': ['S7A', 'S7B']},
     'options': opt(
         'T1 — Standard Business Hours',
         'T2 — Extended Hours / Priority',
         'T3 — 24x7 Critical Support')},
    {'key': 's8Level', 'label': 'Managed Services Level', 'type': 'select', 'required': True,
     'help': 'Required when S8 is selected', 'show_if': {'field': 'services', 'contains': ['S8']},
     'options': opt('M1 — Monitor', 'M2 — Monitor + Coordinate', 'M3 — Operate')},
]


EINVOICING_SECTIONS = [
    contact_section(),
    {
        'id': 'S02',
        'title': 'Business Scope & Legal Entity Structure',
        'subtitle': "Help us understand the shape of the engagement.",
        'fields': [
            {'key': 'entityScopeType', 'label': 'Single entity or multiple entities?', 'type': 'radio',
             'required': True, 'help': 'Determines whether this is a single-entity or group engagement',
             'options': opt('Single entity', 'Multiple entities within UAE',
                            'Multiple entities across multiple countries')},
            {'key': 'entityCount', 'label': 'Number of legal entities in scope', 'type': 'number',
             'required': True, 'min': 1,
             'help': 'Enter 1 or more — the Entity Details below adjust to this number'},
            {'key': 'documentScope', 'label': 'Invoicing scope currently relevant', 'type': 'checkbox',
             'required': True, 'help': 'Document types in scope for eInvoicing compliance',
             'options': opt('Outbound customer invoices', 'Inbound supplier invoices', 'Credit notes',
                            'Debit notes', 'Self-billing or special billing arrangements',
                            'Not sure yet')},
            {'key': 'currentNeedType', 'label': 'Current need / engagement intent', 'type': 'radio',
             'required': True, 'help': 'What you are primarily looking for from KGRN',
             'options': opt('Exploring options', 'Need compliance readiness guidance',
                            'Need implementation support', 'Need platform / ASP subscription',
                            'Need end-to-end managed support', 'Looking for a full solution partner')},
        ],
        # Repeatable sub-form: one block per legal entity in scope.
        'entities': {
            'title': 'Entity Details',
            'subtitle': 'Add one block per legal entity in scope (optional but helps us scope accurately).',
            'fields': EINVOICING_ENTITY_FIELDS,
        },
    },
    {
        'id': 'S03',
        'title': 'Current Finance & Invoicing Environment',
        'subtitle': "A snapshot of how invoicing works today.",
        'fields': [
            {'key': 'invoiceGenerationMethod', 'label': 'How are invoices currently generated?',
             'type': 'checkbox', 'required': True, 'help': 'Current methods used to create & issue invoices',
             'options': opt('ERP system', 'Accounting software', 'Custom in-house system',
                            'Excel / manual process', 'Third-party billing tool',
                            'Different methods across entities')},
            {'key': 'invoiceCentralization', 'label': 'Invoice generation model', 'type': 'radio',
             'required': True, 'help': 'Managed centrally or per branch / entity',
             'options': opt('Centrally', 'Decentralized by branch / entity', 'Hybrid', 'Not sure')},
            {'key': 'processStandardization',
             'label': 'Is the invoicing process standardized across entities?', 'type': 'radio',
             'required': True, 'help': 'Same process & templates across all entities?',
             'options': opt('Yes', 'No', 'Partially', 'Not sure')},
            {'key': 'financeTeamAvailability', 'label': 'Finance team availability for this project',
             'type': 'radio', 'required': True, 'help': 'Can the finance team support implementation?',
             'options': opt('Yes', 'Limited availability', 'No', 'Not sure')},
            {'key': 'itSupportModel', 'label': 'IT or vendor support availability', 'type': 'radio',
             'required': True, 'help': 'Who provides technical support for finance systems',
             'options': opt('Internal IT team', 'External vendor', 'Both', 'No dedicated support',
                            'Not sure')},
        ],
    },
    {
        'id': 'S04',
        'title': 'Technical & Integration Readiness',
        'subtitle': "How you expect to connect to the eInvoicing platform.",
        'fields': [
            {'key': 'implementationApproach', 'label': 'Expected implementation approach', 'type': 'radio',
             'required': True, 'help': 'How you expect to connect to the eInvoicing platform',
             'options': opt('Portal / manual submission', 'File upload / batch-based approach',
                            'Direct system integration', 'Not sure — need guidance')},
            {'key': 'apiReadiness', 'label': 'Does the ERP / system support API-based integration?',
             'type': 'radio', 'required': True, 'help': 'Can the existing system connect via API?',
             'options': opt('Yes', 'No', 'Not sure', 'Needs confirmation by IT/vendor')},
            {'key': 'uatAvailable', 'label': 'Is a test / UAT environment available?', 'type': 'radio',
             'required': False, 'help': 'A non-production environment for testing',
             'options': opt('Yes', 'No', 'Planned', 'Not sure')},
            {'key': 'vendorCoordinationNeeded', 'label': 'Will ERP / vendor coordination be needed?',
             'type': 'radio', 'required': True, 'help': 'Should KGRN coordinate with your ERP vendor?',
             'options': opt('Yes', 'No', 'Possibly', 'Not sure')},
        ],
    },
    {
        'id': 'S05',
        'title': 'Invoice Volume & Transaction Profile',
        'subtitle': "The profile of your invoicing transactions.",
        'fields': [
            {'key': 'transactionProfile', 'label': 'Transaction profile', 'type': 'radio',
             'required': True, 'help': 'Primarily B2B or B2C?',
             'options': opt('Mostly B2B', 'Mostly B2C', 'Mixed', 'Not sure')},
            {'key': 'geographyProfile', 'label': 'Supplier / customer geography', 'type': 'radio',
             'required': True, 'help': 'Where most suppliers & customers are located',
             'options': opt('Mostly UAE domestic', 'Mostly international',
                            'Mixed UAE and international', 'Not sure')},
        ],
    },
    {
        'id': 'S06',
        'title': 'Required Services & Support Expectations',
        'subtitle': "The level of ongoing support you expect.",
        'fields': [
            {'key': 'postGoLiveSupportLevel', 'label': 'Post-go-live support expectation', 'type': 'radio',
             'required': True, 'help': 'Level of ongoing support expected after go-live',
             'options': opt('Platform access only', 'Basic support desk',
                            'Monitoring and issue support', 'End-to-end managed operations', 'Not sure')},
            {'key': 'exceptionHandlingRequired',
             'label': 'Exception handling / issue coordination expected?', 'type': 'radio',
             'required': False, 'help': 'Should KGRN actively manage & resolve submission errors?',
             'options': opt('Yes', 'No', 'Possibly', 'Not sure')},
        ],
    },
    {
        'id': 'S07',
        'title': 'Commercial & Timing Inputs',
        'subtitle': "When you need to be live and how you prefer to contract.",
        'fields': [
            {'key': 'targetGoLiveWindow', 'label': 'Target go-live or decision window', 'type': 'select',
             'required': True, 'help': 'When you need to be live or make a final decision',
             'options': opt('Immediate / urgent', '1-3 months', '3-6 months', '6+ months', 'Not sure')},
            {'key': 'commercialPreference', 'label': 'Commercial / pricing preference', 'type': 'radio',
             'required': True, 'help': 'Preferred commercial structure for the engagement',
             'options': opt('Fixed one-time fee', 'Annual subscription', 'Monthly managed service',
                            'Phased / milestone-based', 'Need recommendation')},
            {'key': 'procurementRequired',
             'label': 'Formal procurement or vendor onboarding required?', 'type': 'radio',
             'required': True, 'help': 'RFP, tender or vendor registration needed before contracting?',
             'options': opt('Yes', 'No', 'Possibly', 'Not sure')},
            {'key': 'decisionOwner', 'label': 'Decision owner / approver', 'type': 'text',
             'required': False, 'help': 'Name & role of the person who will approve the engagement'},
        ],
    },
    {
        'id': 'S08',
        'title': 'Known Constraints & Risk Factors',
        'subtitle': "Anything that could affect the engagement.",
        'fields': [
            {'key': 'knownConstraints', 'label': 'Known constraints or blockers', 'type': 'checkbox',
             'required': False, 'help': 'Any known risks or blockers',
             'options': opt('Internal approvals pending', 'ERP vendor availability uncertain',
                            'Data quality concerns', 'Multiple stakeholders not aligned',
                            'Budget not yet approved', 'Timeline is fixed',
                            'Regulatory deadline pressure', 'None known')},
            {'key': 'notes', 'label': 'Additional notes / context', 'type': 'textarea', 'required': False,
             'help': 'Free-text space for anything extra you want to share with KGRN'},
        ],
    },
    confirmation_section('S09'),
]


# ==================================================================
# 2) External Audit — Group Companies
# ==================================================================
GROUP_AUDIT_ENTITY_FIELDS = [
    {'key': 'companyName', 'label': 'Name of company', 'type': 'text', 'required': True,
     'help': 'Legal name of this group company'},
    {'key': 'lastYearAuditDone', 'label': 'Was last year’s audit done?', 'type': 'radio',
     'required': True, 'options': YES_NO},
    {'key': 'auditCompanyName', 'label': 'Audit company name', 'type': 'text', 'required': True,
     'help': 'Name of the firm that performed last year’s audit',
     'show_if': {'field': 'lastYearAuditDone', 'contains': ['Yes']}},
    {'key': 'annualTurnover2025', 'label': 'Annual turnover 2025', 'type': 'text', 'required': True,
     'placeholder': 'e.g. AED 5,000,000'},
    {'key': 'businessActivities', 'label': 'Business activities', 'type': 'text', 'required': True},
    {'key': 'accountingSoftware', 'label': 'Accounting software', 'type': 'text', 'required': True,
     'placeholder': 'e.g. Tally, Zoho, QuickBooks, Odoo'},
    {'key': 'totalEmployees', 'label': 'Total number of employees', 'type': 'number', 'required': True,
     'min': 0},
    {'key': 'bankAccountsCount', 'label': 'Number of bank accounts', 'type': 'number', 'required': True,
     'min': 0},
    {'key': 'bankNames', 'label': 'Name of the banks', 'type': 'text', 'required': True},
    {'key': 'loansBorrowings', 'label': 'Any loans and borrowings in the entity?', 'type': 'radio',
     'required': True, 'options': YES_NO_NOT_SURE},
    {'key': 'corporateTaxFiling2025', 'label': 'Looking for Corporate Tax return filing for 2025?',
     'type': 'radio', 'required': True, 'options': YES_NO_NOT_SURE},
]

GROUP_AUDIT_SECTIONS = [
    contact_section(),
    {
        'id': 'S02',
        'title': 'Group Companies in Scope',
        'subtitle': "Tell us how many companies in the group need to be covered.",
        'fields': [
            {'key': 'entityCount', 'label': 'Number of companies in the group', 'type': 'number',
             'required': True, 'min': 1,
             'help': 'Enter 1 or more — the company blocks below adjust to this number'},
        ],
        'entities': {
            'title': 'Group Company Details',
            'subtitle': 'Add one block per company in the group.',
            'fields': GROUP_AUDIT_ENTITY_FIELDS,
        },
    },
    confirmation_section('S03'),
]


# ==================================================================
# 3) Valuation
# ==================================================================
VALUATION_SECTIONS = [
    contact_section(extra_fields=[
        {'key': 'officeAddress', 'label': 'Office address', 'type': 'text', 'required': True},
    ]),
    {
        'id': 'S02',
        'title': 'Business & Audit Profile',
        'subtitle': "About the target company's business and audit history.",
        'fields': [
            {'key': 'natureOfBusiness', 'label': 'Nature of business of the target company',
             'type': 'text', 'required': True},
            {'key': 'accountsAudited', 'label': 'Have the accounts of the company been audited?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'auditedUntilYear', 'label': 'Audited until which year', 'type': 'text',
             'required': True, 'placeholder': 'e.g. 2024',
             'show_if': {'field': 'accountsAudited', 'contains': ['Yes']}},
            {'key': 'fy2023Revenue', 'label': 'FY 2023 revenue', 'type': 'text', 'required': True,
             'placeholder': 'e.g. AED 5,000,000'},
        ],
    },
    {
        'id': 'S03',
        'title': 'Capital Structure & Investments',
        'subtitle': "The company's capital structure and investment holdings.",
        'fields': [
            {'key': 'totalAssets', 'label': 'Total assets', 'type': 'number', 'required': True, 'min': 0},
            {'key': 'equity', 'label': 'Equity', 'type': 'number', 'required': True, 'min': 0},
            {'key': 'debt', 'label': 'Debt', 'type': 'number', 'required': True, 'min': 0},
            {'key': 'listedSecuritiesCount', 'label': 'Number of bonds/securities (Listed)',
             'type': 'number', 'required': False, 'min': 0},
            {'key': 'unlistedSecuritiesCount', 'label': 'Number of bonds/securities (Unlisted)',
             'type': 'number', 'required': False, 'min': 0},
            {'key': 'minorityPortfolioCount',
             'label': 'Number of portfolio companies — minority investment holding',
             'type': 'number', 'required': False, 'min': 0},
            {'key': 'majorityPortfolioCount',
             'label': 'Number of portfolio companies — majority investment holding',
             'type': 'number', 'required': False, 'min': 0},
        ],
    },
    {
        'id': 'S04',
        'title': 'Valuation Requirement',
        'subtitle': "What you need this valuation for.",
        'fields': [
            {'key': 'valuationRequirementDescription',
             'label': 'Brief description about the valuation requirement', 'type': 'textarea',
             'required': True},
            {'key': 'otherRemarks', 'label': 'Other remarks', 'type': 'textarea', 'required': False},
        ],
    },
    confirmation_section('S05'),
]


# ==================================================================
# 4) Liquidation Audit
# ==================================================================
LIQUIDATION_SECTIONS = [
    contact_section(extra_fields=[
        {'key': 'location', 'label': 'Location', 'type': 'text', 'required': True},
        {'key': 'establishmentDate', 'label': 'Company establishment date', 'type': 'text',
         'required': True, 'placeholder': 'DD/MM/YYYY'},
    ]),
    {
        'id': 'S02',
        'title': 'Business & Turnover Profile',
        'subtitle': "Recent business activity and prior audit history.",
        'fields': [
            {'key': 'natureOfBusiness', 'label': 'Nature of business activities', 'type': 'text',
             'required': True},
            {'key': 'turnover2023', 'label': 'Turnover for the year 2023', 'type': 'text',
             'required': True},
            {'key': 'turnover2024', 'label': 'Turnover for the year 2024', 'type': 'text',
             'required': True},
            {'key': 'turnover2025Expected', 'label': 'Expected turnover for the year 2025',
             'type': 'text', 'required': True},
            {'key': 'lastYearAuditDone', 'label': 'Have you done last year’s audit?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'auditCompanyName', 'label': 'Audit company name', 'type': 'text', 'required': True,
             'show_if': {'field': 'lastYearAuditDone', 'contains': ['Yes']}},
        ],
    },
    {
        'id': 'S03',
        'title': 'Operations Snapshot',
        'subtitle': "Approximate transaction volumes and systems in use.",
        'fields': [
            {'key': 'monthlySalesTx', 'label': 'Approx. sales transactions per month', 'type': 'number',
             'required': True, 'min': 0},
            {'key': 'monthlyPurchaseTx', 'label': 'Approx. purchase transactions per month',
             'type': 'number', 'required': True, 'min': 0},
            {'key': 'monthlyBankCashTx', 'label': 'Approx. bank and cash transactions per month',
             'type': 'number', 'required': True, 'min': 0},
            {'key': 'accountingSoftware', 'label': 'Accounting software', 'type': 'text',
             'required': True},
            {'key': 'totalEmployees', 'label': 'Total number of employees', 'type': 'number',
             'required': True, 'min': 0},
            {'key': 'shareholdingPattern', 'label': 'Shareholding pattern of the entity',
             'type': 'textarea', 'required': True},
        ],
    },
    {
        'id': 'S04',
        'title': 'Compliance & Risk Status',
        'subtitle': "Open items that could affect the liquidation audit.",
        'fields': [
            {'key': 'corporateTaxStatus', 'label': 'Corporate tax registration status', 'type': 'radio',
             'required': True,
             'options': opt('Registered', 'Not registered', 'Exempt', 'Not sure')},
            {'key': 'openCommitments',
             'label': 'Current status of any open commitments and liabilities, if any',
             'type': 'textarea', 'required': False},
            {'key': 'legalCases', 'label': 'Any legal cases ongoing or expected', 'type': 'radio',
             'required': True, 'options': opt('Yes', 'No', 'Possibly')},
            {'key': 'legalCasesDetails', 'label': 'Legal case details', 'type': 'textarea',
             'required': True,
             'show_if': {'field': 'legalCases', 'contains': ['Yes', 'Possibly']}},
            {'key': 'loansBorrowings', 'label': 'Any loans and borrowings', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'etihadCreditBureauReport', 'label': 'Etihad Credit Bureau report', 'type': 'radio',
             'required': True, 'options': opt('Available', 'Not available', 'Not sure')},
            {'key': 'bankAccountClosed', 'label': 'Bank account closed?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'activeVisaCount', 'label': 'Number of visas available/active', 'type': 'number',
             'required': True, 'min': 0},
            {'key': 'otherMatters', 'label': 'Other matters, if any', 'type': 'textarea',
             'required': False},
        ],
    },
    {
        'id': 'S05',
        'title': 'Engagement Timing',
        'subtitle': "Tell us more about the business and when you need the service.",
        'fields': [
            {'key': 'serviceTimingDetails',
             'label': 'Details of your business and when you need the service', 'type': 'textarea',
             'required': True},
        ],
    },
    confirmation_section('S06'),
]


# ==================================================================
# 5) Inventory Count
# ==================================================================
INVENTORY_COUNT_SECTIONS = [
    contact_section(extra_fields=[
        {'key': 'establishmentDate', 'label': 'Company establishment date', 'type': 'text',
         'required': True, 'placeholder': 'DD/MM/YYYY'},
    ]),
    {
        'id': 'S02',
        'title': 'Inventory Profile',
        'subtitle': "What is being counted and how.",
        'fields': [
            {'key': 'locationDetails',
             'label': 'Location details (all the locations that need to be covered)',
             'type': 'textarea', 'required': True},
            {'key': 'natureOfBusiness', 'label': 'Nature of business', 'type': 'text', 'required': True},
            {'key': 'inventoryType', 'label': 'Type of inventory', 'type': 'text', 'required': True},
            {'key': 'verificationBasis',
             'label': 'Are you looking for 100% physical verification or a sampling basis?',
             'type': 'radio', 'required': True,
             'options': opt('100% physical verification', 'Sampling basis')},
            {'key': 'samplingPercentage', 'label': 'Sampling percentage to be verified', 'type': 'number',
             'required': True, 'min': 0,
             'show_if': {'field': 'verificationBasis', 'contains': ['Sampling basis']}},
            {'key': 'fixedAssetsTagged', 'label': 'Are the fixed assets already tagged?', 'type': 'radio',
             'required': True, 'options': opt('Yes', 'No', 'Partially')},
            {'key': 'totalInventoryValue', 'label': 'Total value of inventory', 'type': 'text',
             'required': True, 'placeholder': 'e.g. AED 1,000,000'},
        ],
    },
    {
        'id': 'S03',
        'title': 'Count Schedule',
        'subtitle': "The proposed dates for the count.",
        'fields': [
            {'key': 'countStartDate', 'label': 'Proposed count date — start', 'type': 'text',
             'required': True, 'placeholder': 'DD/MM/YYYY'},
            {'key': 'countEndDate', 'label': 'Proposed count date — end', 'type': 'text',
             'required': True, 'placeholder': 'DD/MM/YYYY'},
        ],
    },
    {
        'id': 'S04',
        'title': 'Additional Information',
        'subtitle': "Anything else that helps us plan the count.",
        'fields': [
            {'key': 'otherMatters', 'label': 'Other matters, if any', 'type': 'textarea',
             'required': False},
            {'key': 'serviceTimingDetails',
             'label': 'Details of your business and when you need the service', 'type': 'textarea',
             'required': True},
        ],
    },
    confirmation_section('S05'),
]


# ==================================================================
# 6) ADGM Audit Fee Assessment
# ==================================================================
ADGM_AUDIT_SECTIONS = [
    contact_section(
        extra_fields=[
            {'key': 'businessActivities', 'label': 'Business activities per license', 'type': 'text',
             'required': True},
            {'key': 'officeAddress', 'label': 'Registered office address', 'type': 'text',
             'required': True},
        ],
        mobile_required=False,
    ),
    {
        'id': 'S02',
        'title': 'Financial Profile of the Parent',
        'subtitle': "Key financials used to size the audit.",
        'fields': [
            {'key': 'yearOfAudit', 'label': 'Year of audit', 'type': 'text', 'required': True,
             'placeholder': 'e.g. 2026'},
            {'key': 'annualRevenueParent', 'label': 'Annual revenue/turnover of the parent (USD)',
             'type': 'text', 'required': True},
            {'key': 'investmentEquityShares', 'label': 'Investment in equity shares (USD)', 'type': 'text',
             'required': False},
            {'key': 'inventoriesValue', 'label': 'Inventories (USD)', 'type': 'text', 'required': False},
            {'key': 'totalEmployees', 'label': 'Number of employees', 'type': 'number', 'required': True,
             'min': 0},
        ],
    },
    {
        'id': 'S03',
        'title': 'Group Structure',
        'subtitle': "Does the parent have subsidiaries, and how should they be covered?",
        'fields': [
            {'key': 'hasSubsidiaries', 'label': 'Does the parent entity have investment in subsidiaries?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'subsidiariesCount', 'label': 'Number of subsidiaries', 'type': 'number',
             'required': True, 'min': 0,
             'show_if': {'field': 'hasSubsidiaries', 'contains': ['Yes']}},
            {'key': 'subsidiariesRevenue', 'label': 'Annual revenue/turnover of each subsidiary (USD)',
             'type': 'textarea', 'required': True,
             'show_if': {'field': 'hasSubsidiaries', 'contains': ['Yes']}},
            {'key': 'subsidiariesAuditedByOthers',
             'label': 'Are the subsidiaries’ individual accounts audited by another auditor?',
             'type': 'radio', 'required': True, 'options': YES_NO,
             'show_if': {'field': 'hasSubsidiaries', 'contains': ['Yes']}},
            {'key': 'includeSubsidiariesAuditByUs',
             'label': 'Do you want us to include subsidiaries’ annual accounts audited by us?',
             'type': 'radio', 'required': True, 'options': YES_NO,
             'help': 'We can undertake the audit of those subsidiaries established in the UAE',
             'show_if': {'field': 'hasSubsidiaries', 'contains': ['Yes']}},
            {'key': 'reportToShareholderAuditors',
             'label': 'Are we required to report group audit findings to the auditors of the shareholder company?',
             'type': 'radio', 'required': True, 'options': YES_NO},
        ],
    },
    {
        'id': 'S04',
        'title': 'Scope & Timeline',
        'subtitle': "The scope of the audit and any deadlines.",
        'fields': [
            {'key': 'scopeOfAudit', 'label': 'Scope of audit', 'type': 'checkbox', 'required': True,
             'options': opt('Standalone (Parent)', 'Consolidation (Parent)', 'Standalone (Subsidiary)')},
            {'key': 'auditDeadlines', 'label': 'Are there any deadlines for the audit?', 'type': 'text',
             'required': False},
            {'key': 'otherMatters', 'label': 'Any other matters', 'type': 'textarea', 'required': False},
        ],
    },
    confirmation_section('S05'),
]


# ==================================================================
# 7) Bookkeeping & Tax Consultation
# ==================================================================
BOOKKEEPING_TAX_SECTIONS = [
    contact_section(extra_fields=[
        {'key': 'location', 'label': 'Location', 'type': 'text', 'required': True},
        {'key': 'establishmentDate', 'label': 'Company establishment date', 'type': 'text',
         'required': True, 'placeholder': 'DD/MM/YYYY'},
    ]),
    {
        'id': 'S02',
        'title': 'Business Profile',
        'subtitle': "Turnover and prior audit history.",
        'fields': [
            {'key': 'natureOfBusiness', 'label': 'Nature of business', 'type': 'text', 'required': True},
            {'key': 'turnover2025', 'label': 'Turnover for the year 2025', 'type': 'text',
             'required': True},
            {'key': 'turnover2026Expected', 'label': 'Expected turnover for the year 2026',
             'type': 'text', 'required': True},
            {'key': 'lastYearAuditDone', 'label': 'Have you done last year’s audit?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'auditCompanyName', 'label': 'Audit company name', 'type': 'text', 'required': True,
             'show_if': {'field': 'lastYearAuditDone', 'contains': ['Yes']}},
        ],
    },
    {
        'id': 'S03',
        'title': 'Transactions & Systems',
        'subtitle': "Approximate transaction volumes and systems in use.",
        'fields': [
            {'key': 'monthlySalesTx', 'label': 'Approx. sales transactions per month', 'type': 'number',
             'required': True, 'min': 0},
            {'key': 'monthlyPurchaseTx', 'label': 'Approx. purchase transactions per month',
             'type': 'number', 'required': True, 'min': 0},
            {'key': 'monthlyBankCashTx', 'label': 'Approx. bank and cash transactions per month',
             'type': 'number', 'required': True, 'min': 0},
            {'key': 'accountingSoftware', 'label': 'Accounting software', 'type': 'text',
             'required': True},
            {'key': 'totalEmployees', 'label': 'Total number of employees', 'type': 'number',
             'required': True, 'min': 0},
            {'key': 'bankAccountsAndPaymentMethod', 'label': 'Number of bank accounts and payment method',
             'type': 'textarea', 'required': True},
        ],
    },
    {
        'id': 'S04',
        'title': 'Compliance Requirements',
        'subtitle': "Filing needs and related-party exposure.",
        'fields': [
            {'key': 'vatReturnFilingNeeded', 'label': 'Are you looking for VAT return filing?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'corporateTaxFilingNeeded',
             'label': 'Are you looking for corporate tax return filing?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'groupStructure',
             'label': 'Group structure (if applicable, provide details of parent and subsidiary companies)',
             'type': 'textarea', 'required': False},
            {'key': 'relatedPartyPersons', 'label': 'Related party / connected persons', 'type': 'textarea',
             'required': False},
            {'key': 'transferPricingConsiderations',
             'label': 'Any transfer pricing considerations or cross-border transactions?', 'type': 'radio',
             'required': True, 'options': YES_NO_NOT_SURE},
            {'key': 'intercompanyLoansFees',
             'label': 'Any intercompany loans, management fees, or cost allocations?', 'type': 'radio',
             'required': True, 'options': YES_NO_NOT_SURE},
        ],
    },
    {
        'id': 'S05',
        'title': 'Service Preferences',
        'subtitle': "How you'd like the engagement to run.",
        'fields': [
            {'key': 'backlogUpdationNeeded',
             'label': 'Does any backlog accounts updation need to be done?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'backlogTransactionsCount', 'label': 'Approx. number of backlog transactions',
             'type': 'number', 'required': True, 'min': 0,
             'show_if': {'field': 'backlogUpdationNeeded', 'contains': ['Yes']}},
            {'key': 'officeVisitNeeded',
             'label': 'Are you looking for an accountant to visit your office?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'officeVisitsPerMonth', 'label': 'Number of visits each month', 'type': 'number',
             'required': True, 'min': 0,
             'show_if': {'field': 'officeVisitNeeded', 'contains': ['Yes']}},
            {'key': 'otherMatters', 'label': 'Other matters, if any', 'type': 'textarea',
             'required': False},
        ],
    },
    confirmation_section('S06'),
]


# ==================================================================
# 8) Corporate Tax Consultation & Transfer Pricing
# ==================================================================
CORPORATE_TAX_TP_SECTIONS = [
    contact_section(),
    {
        'id': 'S02',
        'title': 'Entity / Group Structure',
        'subtitle': "Where the entities are registered and how they're structured.",
        'fields': [
            {'key': 'serviceScope', 'label': 'Is the service required for an entity or a group of companies?',
             'type': 'radio', 'required': True,
             'options': opt('Single entity', 'Group of companies')},
            {'key': 'groupStructureNote',
             'label': 'Group structure / names of the entities in the group', 'type': 'textarea',
             'required': False, 'help': 'Attach or describe the group structure if applicable'},
            {'key': 'entitiesRegisteredLocation', 'label': 'Where are the entities registered?',
             'type': 'text', 'required': True},
            {'key': 'freezoneRegistered',
             'label': 'Are the entities registered in Freezones?', 'type': 'radio', 'required': True,
             'options': opt('Yes', 'No', 'Partially')},
            {'key': 'freezoneComplianceNote',
             'label': 'Is it conducting operations in line with free zone regulations and will it maintain its tax-free status?',
             'type': 'textarea', 'required': False,
             'show_if': {'field': 'freezoneRegistered', 'contains': ['Yes', 'Partially']}},
            {'key': 'shareholdingPattern', 'label': 'Shareholding pattern of the entities',
             'type': 'textarea', 'required': True},
            {'key': 'legalBusinessCapitalStructure',
             'label': 'Legal structure, business model, and capital structure of the entities',
             'type': 'textarea', 'required': True},
        ],
    },
    {
        'id': 'S03',
        'title': 'Related Party & Transfer Pricing',
        'subtitle': "Transactions with related parties and TP compliance history.",
        'fields': [
            {'key': 'relatedPartyTransactionTypes',
             'label': 'Type of transactions with related parties and connected persons', 'type': 'textarea',
             'required': True},
            {'key': 'armsLengthCompliance',
             'label': 'Are the existing related party transactions compliant with arm’s length TP requirements?',
             'type': 'radio', 'required': True, 'options': YES_NO_NOT_SURE},
            {'key': 'crossBorderMainlandFreezone',
             'label': 'Are there any cross-border transactions involving mainland and free zone entities?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'historicalTPDocumentation', 'label': 'Historical TP documentation', 'type': 'radio',
             'required': True, 'options': opt('Available', 'Not available', 'Partial')},
        ],
    },
    {
        'id': 'S04',
        'title': 'Tax Group & Compliance Status',
        'subtitle': "Awareness and current compliance posture.",
        'fields': [
            {'key': 'managementAwareTaxGroup', 'label': 'Is management aware about the Tax Group?',
             'type': 'radio', 'required': True, 'options': YES_NO_NOT_SURE},
            {'key': 'separateTaxDepartment', 'label': 'Is there a separate tax department in your organisation?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'esrCbcrFilingSubmitted',
             'label': 'Have the entities submitted ESR filing and CbCR filing in the last year?',
             'type': 'radio', 'required': True,
             'options': opt('Yes', 'No', 'Partially', 'Not applicable')},
            {'key': 'withholdingTaxOtherCountries',
             'label': 'Are the entities having any withholding tax deduction in other countries?',
             'type': 'radio', 'required': True, 'options': YES_NO_NOT_SURE},
            {'key': 'foreignTaxPaidNote',
             'label': 'Have foreign branches/PEs paid any taxes in other countries?', 'type': 'textarea',
             'required': False},
        ],
    },
    {
        'id': 'S05',
        'title': 'Financial & Operational Profile',
        'subtitle': "Loans, fixed assets and operating substance.",
        'fields': [
            {'key': 'loansBorrowingsAllocated',
             'label': 'Are there any loans and borrowings in the entities, properly allocated between them?',
             'type': 'radio', 'required': True,
             'options': opt('Yes', 'No', 'Not applicable')},
            {'key': 'loansBorrowingsNote', 'label': 'Loans and borrowings — additional detail',
             'type': 'textarea', 'required': False},
            {'key': 'fixedAssetsRegisterMaintained', 'label': 'Do the entities maintain a fixed assets register?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'natureOfBusinessActivities', 'label': 'Nature of business activities of the entities',
             'type': 'textarea', 'required': True},
            {'key': 'operatingSubstanceDetails',
             'label': 'Are the entities’ operating activities substantiated with sufficient resources?',
             'type': 'textarea', 'required': False,
             'help': 'Volume of transactions, number of employees, directors’ residency status, etc.'},
            {'key': 'lastYearTurnover', 'label': 'Last year turnover', 'type': 'text', 'required': True},
            {'key': 'expectedTurnoverCurrentYear', 'label': 'Expected turnover for the current year',
             'type': 'text', 'required': True},
            {'key': 'totalEmployees', 'label': 'Number of employees', 'type': 'number', 'required': True,
             'min': 0},
        ],
    },
    {
        'id': 'S06',
        'title': 'International Activities',
        'subtitle': "Interests and income outside the UAE.",
        'fields': [
            {'key': 'participatingInterestOutsideUAE',
             'label': 'Did the entity hold participating interest in entities outside the UAE?',
             'type': 'radio', 'required': True, 'options': YES_NO},
            {'key': 'participatingInterestPercentage', 'label': 'Percentage of interest', 'type': 'number',
             'required': True, 'min': 0,
             'show_if': {'field': 'participatingInterestOutsideUAE', 'contains': ['Yes']}},
            {'key': 'passiveIncomeOutsideUAE',
             'label': 'Did the entity receive passive income from outside the UAE?', 'type': 'radio',
             'required': True, 'options': YES_NO},
            {'key': 'passiveIncomeNature', 'label': 'Nature of the passive income', 'type': 'text',
             'required': True,
             'show_if': {'field': 'passiveIncomeOutsideUAE', 'contains': ['Yes']}},
            {'key': 'ipDetails', 'label': 'Details of intellectual property (IP) within the group',
             'type': 'textarea', 'required': False},
        ],
    },
    {
        'id': 'S07',
        'title': 'Future Plans & Services Required',
        'subtitle': "What's ahead, and which services you need from KGRN.",
        'fields': [
            {'key': 'futureBusinessPlans', 'label': 'Future business plans', 'type': 'textarea',
             'required': False},
            {'key': 'servicesRequired', 'label': 'Corporate tax consulting services required',
             'type': 'checkbox', 'required': True,
             'options': opt(
                 'Corporate Tax — Assessment and implementation',
                 'Corporate Tax — Taxable income calculation and return submission',
                 'Transfer pricing services',
                 'Corporate Tax — Training')},
        ],
    },
    confirmation_section('S08'),
]


# ==================================================================
# Form registry
# ==================================================================
DISCOVERY_FORMS = {
    'einvoicing': {'label': 'eInvoicing', 'sections': EINVOICING_SECTIONS},
    'group_audit': {'label': 'External Audit - Group Companies', 'sections': GROUP_AUDIT_SECTIONS},
    'valuation': {'label': 'Valuation', 'sections': VALUATION_SECTIONS},
    'liquidation': {'label': 'Liquidation Audit', 'sections': LIQUIDATION_SECTIONS},
    'inventory_count': {'label': 'Inventory Count', 'sections': INVENTORY_COUNT_SECTIONS},
    'adgm_audit': {'label': 'ADGM Audit Fee Assessment', 'sections': ADGM_AUDIT_SECTIONS},
    'bookkeeping_tax': {'label': 'Bookkeeping & Tax Consultation', 'sections': BOOKKEEPING_TAX_SECTIONS},
    'corporate_tax_tp': {'label': 'Corporate Tax & Transfer Pricing', 'sections': CORPORATE_TAX_TP_SECTIONS},
}


def form_selection():
    """(value, label) pairs for the crm.lead 'Discovery Form' selection field."""
    return [(key, spec['label']) for key, spec in DISCOVERY_FORMS.items()]


def get_sections(form_type):
    """Sections for a given form type, falling back to eInvoicing if unset/unknown."""
    spec = DISCOVERY_FORMS.get(form_type) or DISCOVERY_FORMS['einvoicing']
    return spec['sections']


def get_label(form_type):
    spec = DISCOVERY_FORMS.get(form_type) or DISCOVERY_FORMS['einvoicing']
    return spec['label']


def iter_fields(sections, include_entities=False):
    """Yield (section, field) for every top-level field in the given sections."""
    for section in sections:
        for field in section['fields']:
            yield section, field
        if include_entities and section.get('entities'):
            for field in section['entities']['fields']:
                yield section, field


def field_label(sections, key):
    """Return the human label for a field key (entity fields included)."""
    for _section, field in iter_fields(sections, include_entities=True):
        if field['key'] == key:
            return field['label']
    return key


def entity_fields(sections):
    """Return the repeatable per-entity field spec for these sections, or []."""
    for section in sections:
        if section.get('entities'):
            return section['entities']['fields']
    return []
