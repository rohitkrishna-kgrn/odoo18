# -*- coding: utf-8 -*-
"""
Single source of truth for the Client Discovery Form.

The same structure drives:
  * the public QWeb form rendering (controllers/main.py -> templates/discovery_form.xml)
  * server-side parsing / validation of the submitted payload
  * the human-readable HTML summary stored in the pipeline record's notebook

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
show_if   : optional {'field': <sibling key>, 'contains': [values]} -> conditional
            visibility (currently used inside the per-entity sub-form)
"""


def opt(*labels):
    """Build a list of {'value','label'} options where value == label."""
    return [{'value': l, 'label': l} for l in labels]


# --- Per-entity sub-form (repeats once per legal entity in scope) -------------
# All base entity fields are mandatory; the conditional S6/S7/S8 selects are
# validated only while visible (see the show_if logic in the front-end).
ENTITY_FIELDS = [
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


DISCOVERY_SECTIONS = [
    {
        'id': 'S01',
        'title': 'Company & Contact Information',
        'subtitle': "Tell us who you are so we can address the engagement correctly.",
        'fields': [
            {'key': 'legalCompanyName', 'label': 'Legal company name', 'type': 'text',
             'required': True, 'prefill': 'company_name',
             'help': 'Full registered legal name of the company'},
            {'key': 'tradeName', 'label': 'Trading name', 'type': 'text', 'required': False,
             'help': 'Commercial / trade name if different from the legal name'},
            {'key': 'headOfficeCountry', 'label': 'Primary country of operation', 'type': 'select',
             'required': True, 'other': True,
             'help': 'Where the head office / primary operations are based',
             'options': opt('United Arab Emirates', 'Saudi Arabia', 'Qatar', 'Oman', 'Bahrain',
                            'Kuwait', 'India', 'United Kingdom', 'United States', 'Other')},
            {'key': 'industrySector', 'label': 'Industry / sector', 'type': 'select',
             'required': True, 'other': True, 'help': 'Your primary industry sector',
             'options': opt('Trading', 'Manufacturing', 'Retail', 'Distribution', 'Services',
                            'Real Estate', 'Hospitality', 'Healthcare', 'Logistics', 'Construction',
                            'Technology', 'Financial Services', 'Other')},
            {'key': 'primaryContactName', 'label': 'Primary contact name', 'type': 'text',
             'required': True, 'prefill': 'contact_name',
             'help': 'Full name of the main point of contact'},
            {'key': 'primaryContactRole', 'label': 'Primary contact role', 'type': 'select',
             'required': True, 'other': True, 'help': 'Role / designation of the primary contact',
             'options': opt('CFO / Finance Head', 'Finance Manager', 'Tax Manager', 'IT Manager',
                            'Operations Manager', 'Business Owner', 'Procurement',
                            'Consultant / Advisor', 'Other')},
            {'key': 'primaryContactEmail', 'label': 'Business email', 'type': 'email',
             'required': True, 'prefill': 'email',
             'help': 'Work email address for correspondence'},
            {'key': 'primaryContactMobile', 'label': 'Phone number', 'type': 'phone',
             'required': True, 'prefill': 'phone',
             'placeholder': '+971 50 000 0000',
             'help': 'Mobile or direct phone with international dial code'},
        ],
    },
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
            'fields': ENTITY_FIELDS,
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
    {
        'id': 'S09',
        'title': 'Submission Confirmation & Signature',
        'subtitle': "Confirm accuracy and sign to authorise the submission.",
        'fields': [
            {'key': 'submissionConfirmed', 'label': 'I confirm the information provided is accurate.',
             'type': 'checkbox_single', 'required': True,
             'help': 'Must be checked to enable submission'},
            {'key': 'signatureData', 'label': 'Signature', 'type': 'signature', 'required': True,
             'help': 'Draw your signature to authorise the submission'},
        ],
    },
]


def iter_fields(include_entities=False):
    """Yield (section, field) for every top-level field across all sections."""
    for section in DISCOVERY_SECTIONS:
        for field in section['fields']:
            yield section, field
        if include_entities and section.get('entities'):
            for field in section['entities']['fields']:
                yield section, field


def field_label(key):
    """Return the human label for a field key (entity fields included)."""
    for _section, field in iter_fields(include_entities=True):
        if field['key'] == key:
            return field['label']
    return key


def entity_fields():
    """Return the repeatable per-entity field spec, or []."""
    for section in DISCOVERY_SECTIONS:
        if section.get('entities'):
            return section['entities']['fields']
    return []
