# -*- coding: utf-8 -*-
"""Static proposal content, transcribed verbatim from the Node/puppeteer
generator in pdf.js (`proposalHtml`) so the Odoo PDF carries the same wording.

Only the *static* narrative blocks live here. Everything that varies per
quotation — scope, methodology, deliverables, commercials — comes from the
products on the order lines and the editable Proposal tab.
"""

# ── Section 6: delivery methodology framework ────────────────────────────────
# DELIVERY_PHASES zipped with PHASE_DETAIL, which is what pdf.js actually renders.
DELIVERY_PHASES = [
    ('1', 'Clarify & Align',
     'Engage key stakeholders to confirm the engagement intent, finalise scope '
     'boundaries, agree on the commercial structure, clarify the entity and '
     'dependency landscape, and establish the practical starting assumptions '
     'that will govern delivery.'),
    ('2', 'Assess & Prepare',
     'Conduct a structured review of the current-state environment, identify '
     'practical dependencies, surface any material readiness considerations — '
     'including data, systems, and organisational factors — before execution '
     'commences.'),
    ('3', 'Structure & Execute',
     'Progress the agreed delivery activities in a controlled and properly '
     'sequenced manner, coordinating across the relevant internal and external '
     'stakeholders, managing dependencies, and maintaining delivery discipline '
     'throughout.'),
    ('4', 'Activate & Validate',
     'Drive toward activation or validate operational go-live, confirming that '
     'all readiness conditions have been satisfied, assumptions have held, and '
     'immediate post-activation requirements are understood and in hand.'),
    ('5', 'Stabilise & Evolve',
     "Establish clarity around the immediate post-engagement operating model, "
     "manage the transition period, capture lessons learned, and support the "
     "client's transition to the next stage of their eInvoicing journey where "
     "relevant."),
]

# ── Section 7: guiding principles ────────────────────────────────────────────
GUIDING_PRINCIPLES = [
    ('Scope discipline',
     'Clear boundaries define what is in and out of scope. Any material shift is '
     'subject to formal review and commercial alignment before additional work '
     'commences.'),
    ('Dependency transparency',
     'All known dependencies, risks, and assumptions are surfaced upfront and '
     'managed openly. Where dependencies shift, the engagement adapts accordingly.'),
    ('Stakeholder alignment',
     'The right people — finance, IT, operations, and leadership — are engaged at '
     'the right time to ensure informed decisions and smooth progression.'),
    ('Commercial clarity',
     'Fee structures reflect the actual nature and boundaries of the work. There '
     'are no padded estimates or obscured assumptions built into the commercial '
     'structure.'),
    ('Escalation structure',
     'Any concern, change request, or emerging risk is escalated through an agreed '
     'framework — not left unmanaged or allowed to compound over time.'),
]

# ── Section 8: assumptions & dependencies ────────────────────────────────────
ASSUMPTIONS = [
    'Timely access to relevant client stakeholders, decision-makers, and process '
    'owners throughout the engagement lifecycle.',
    'Availability of required business, process, and systems information in a '
    'format and timeframe suitable for engagement purposes.',
    'Clarity on entity scope, transaction scope, and the underlying operating '
    'model, confirmed within a reasonable period of engagement commencement.',
    'Timely completion of required approvals, procurement steps, sign-offs, and '
    "contracting formalities on the client's side.",
    'No material change in the understood scope, complexity, or dependency profile '
    'without a formal change request and commercial review.',
    "Cooperation from the client's internal teams across finance, tax, IT, "
    'procurement, and operations throughout all delivery phases.',
    'Where third-party vendors or system integrators are involved, the client will '
    'provide reasonable coordination support and access management throughout.',
    "The client's technical environment and existing systems are broadly capable of "
    'supporting the agreed implementation approach; any material deviation will be '
    'flagged for review.',
    'All required regulatory registrations, platform credentials, and authority '
    "access are in place or will be arranged promptly by the client's designated team.",
    "The client's internal testing and UAT resources are available in the timeframes "
    'required for controlled go-live validation activities.',
]

# ── Section 9: exclusions ────────────────────────────────────────────────────
EXCLUSIONS = [
    'Formal legal, tax, or regulatory opinion issuance or legal advisory services.',
    'Custom software development or bespoke system build work.',
    'Procurement, purchasing, or vendor selection services on behalf of the client.',
    'Enterprise-wide transformation services outside the defined eInvoicing scope.',
    'Broader organisational change management programmes.',
]

# ── Section 11: next steps ───────────────────────────────────────────────────
NEXT_STEPS = [
    'Confirm which service line or combination of services best reflects the current '
    'requirement and preferred engagement model.',
    'Identify and confirm the relevant internal stakeholders who will be involved in '
    'commercial and operational alignment.',
    'Clarify any outstanding scope, commercial, or timeline questions that may affect '
    'the final engagement structure.',
    'Move into the formal proposal acceptance and engagement issuance stage for the '
    'agreed service path.',
]

# ── Section 1: executive summary (second paragraph is always shown) ──────────
EXEC_SUMMARY_TAIL = (
    'The eInvoicing landscape is evolving rapidly across the UAE and broader GCC, '
    'with regulatory mandates, platform adoption requirements, and operational '
    'readiness pressures converging into a defined and time-sensitive compliance '
    'journey. Organisations that engage early — with the right advisory and '
    'implementation support — are better positioned to meet requirements on time, '
    'avoid disruption, and build a solid operational foundation for ongoing '
    'compliance. KGRN brings a structured, commercially transparent, and practically '
    'grounded approach to every eInvoicing engagement, drawing on direct experience '
    'across the platform, regulatory, and operational dimensions of this journey.'
)

# ── Section 2: discovery snapshot labels ─────────────────────────────────────
# Keys match the payload written by crm_extended_rk's discovery schema.
DISCOVERY_LABELS = [
    ('entityScopeType', 'Entity scope'),
    ('entityCount', 'Number of legal entities in scope'),
    ('documentScope', 'Invoicing scope'),
    ('currentNeedType', 'Current need'),
    ('invoiceGenerationMethod', 'Invoice generation method'),
    ('processStandardization', 'Invoice process standardised'),
    ('implementationApproach', 'Expected implementation approach'),
    ('apiReadiness', 'API / integration readiness'),
    ('uatAvailable', 'UAT environment available'),
    ('vendorCoordinationNeeded', 'ERP / vendor coordination needed'),
    ('outboundVolumeBand', 'Annual outbound invoice volume'),
    ('inboundVolumeBand', 'Annual inbound invoice volume'),
    ('postGoLiveSupportLevel', 'Post-go-live support expectation'),
    ('targetGoLiveWindow', 'Target go-live or decision window'),
    ('knownConstraints', 'Known constraints'),
]

# ── Default editable terms & conditions ──────────────────────────────────────
# Mirrors PAYMENT_TERMS_BLOCK in pdf.js. Stored on the quotation as HTML so the
# sales team can edit it per proposal; the report renders whatever is stored.
DEFAULT_TERMS_HTML = """<div>
  <div><strong>1. Scope of Engagement</strong></div>
  <p>The services shall be provided in accordance with all discussions, communications, proposals, commitments, and mutually agreed terms established from the beginning of the engagement process up to the final service engagement confirmation. All agreed deliverables, timelines, responsibilities, and commercial terms shall remain applicable throughout the engagement period.</p>
  <div><strong>2. No Change Policy</strong></div>
  <p>Once the service engagement has been confirmed and approved by both parties, no unilateral changes, modifications, or deviations shall be made to the agreed scope, pricing, timelines, or service conditions unless mutually agreed in writing by both parties.</p>
  <div><strong>3. Payment Terms</strong></div>
  <ul>
    <li>All professional services are <strong>one-time, fixed-fee engagements</strong> — invoiced upon commencement or at the agreed milestone. The Annual ASP / Subscription Service (S6) is the only <strong>recurring annual fee</strong>, billed per entity per year.</li>
    <li>Payments shall be made as per the agreed commercial proposal/invoice schedule.</li>
    <li>All invoices must be settled within the agreed payment period from the invoice date.</li>
    <li>Delayed payments may impact service continuity, support timelines, or project deliverables.</li>
    <li>Any additional services requested outside the agreed scope shall be subject to separate commercial approval and billing.</li>
  </ul>
  <div><strong>4. Organizational Support &amp; Responsibilities</strong></div>
  <p>The client organization shall provide all necessary cooperation, approvals, access, information, and operational support required for smooth execution of services, including:</p>
  <ul>
    <li>Timely sharing of documents, credentials, and project requirements.</li>
    <li>Availability of key stakeholders for coordination and approvals.</li>
    <li>Internal support for implementation, testing, and communication activities.</li>
    <li>Prompt response to queries or dependency-related requests.</li>
  </ul>
  <p>Any delays caused due to lack of organizational support, approvals, or dependency constraints may result in revised timelines and delivery schedules.</p>
  <div><strong>5. Service Continuity</strong></div>
  <p>The service provider shall ensure professional support and execution based on the agreed engagement terms and organizational coordination. Both parties agree to maintain transparent communication for smooth project delivery and operational continuity.</p>
  <div><strong>6. Confidentiality</strong></div>
  <p>All business, operational, and commercial information exchanged during the engagement shall remain confidential and shall not be disclosed to any third party without prior written consent from the respective party.</p>
  <div><strong>7. Acceptance</strong></div>
  <p>Commencement of services and/or payment against invoices shall be considered acceptance of these payment terms and engagement conditions by the client organization.</p>
</div>"""
