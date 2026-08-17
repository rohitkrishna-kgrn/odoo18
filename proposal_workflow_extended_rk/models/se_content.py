# -*- coding: utf-8 -*-
"""Service Engagement Agreement content, transcribed verbatim from `seHtml`
and `AGREEMENT_LIBRARY` in pdf.js. Extracted programmatically from the source
file rather than retyped, so the legal wording is character-for-character.

`[Client Legal Name]` and `[Date]` are substituted at render time, exactly as
the JS does.
"""

# ── Agreement clauses (numbered cards on the terms pages) ────────────────────
AGREEMENT_LIBRARY = [
    ('Parties and Background',
     'This Engagement Agreement (the “Agreement”) is entered into on [Date] between KGRN '
     'Chartered Accountants LLC (“KGRN”) and [Client Legal Name] (the “Client”). The '
     'Client wishes to engage KGRN in connection with certain eInvoicing-related services,'
     ' and KGRN has agreed to provide such services subject to the terms and conditions '
     'set out in this Agreement, together with the applicable schedules, appendices, and '
     'commercial terms incorporated herein.'),
    ('Definitions and Interpretation',
     'For the purposes of this Agreement, defined terms may include Services, Commercials,'
     ' Assumptions and Dependencies, Managed Services Terms, Support Terms, or Rollout '
     'Terms where relevant. In the event of any inconsistency between the main body of '
     'this Agreement and any schedule, the core legal protections of the main body should '
     'ordinarily prevail unless explicitly stated otherwise.'),
    ('Appointment and Scope of Services',
     'The Client hereby appoints KGRN to provide the Services described in this Agreement '
     'and the applicable schedules, and KGRN accepts such appointment subject to the terms'
     ' and conditions herein. KGRN shall provide the Services in accordance with the '
     'agreed scope, subject always to the assumptions, dependencies, exclusions, and '
     'commercial structure reflected in the relevant schedules.'),
    ('Client Responsibilities and Cooperation',
     'The Client acknowledges that the timely and effective provision of the Services '
     'depends on the Client’s cooperation and fulfillment of its responsibilities under '
     'this Agreement, including timely access to personnel, stakeholders, systems '
     'information, documentation, required inputs, approvals, internal coordination, and '
     'client-side obligations described in the schedules.'),
    ('Payment Terms',
     '<strong>1. Scope of Engagement</strong><br>The services shall be provided in '
     'accordance with all discussions, communications, proposals, commitments, and '
     'mutually agreed terms established from the beginning of the engagement process up to'
     ' the final service engagement confirmation. All agreed deliverables, timelines, '
     'responsibilities, and commercial terms shall remain applicable throughout the '
     'engagement period.<br><br><strong>2. No Change Policy</strong><br>Once the service '
     'engagement has been confirmed and approved by both parties, no unilateral changes, '
     'modifications, or deviations shall be made to the agreed scope, pricing, timelines, '
     'or service conditions unless mutually agreed in writing by both '
     'parties.<br><br><strong>3. Payment Terms</strong><br>Payments shall be made as per '
     'the agreed commercial proposal/invoice schedule. All invoices must be settled within'
     ' the agreed payment period from the invoice date. Delayed payments may impact '
     'service continuity, support timelines, or project deliverables. Any additional '
     'services requested outside the agreed scope shall be subject to separate commercial '
     'approval and billing.<br><br><strong>4. Organisational Support &amp; '
     'Responsibilities</strong><br>The client organisation shall provide all necessary '
     'cooperation, approvals, access, information, and operational support required for '
     'smooth execution of services, including: timely sharing of documents, credentials, '
     'and project requirements; availability of key stakeholders for coordination and '
     'approvals; internal support for implementation, testing, and communication '
     'activities; and prompt response to queries or dependency-related requests. Any '
     'delays caused due to lack of organisational support, approvals, or dependency '
     'constraints may result in revised timelines and delivery '
     'schedules.<br><br><strong>5. Service Continuity</strong><br>The service provider '
     'shall ensure professional support and execution based on the agreed engagement terms'
     ' and organisational coordination. Both parties agree to maintain transparent '
     'communication for smooth project delivery and operational '
     'continuity.<br><br><strong>6. Confidentiality</strong><br>All business, operational,'
     ' and commercial information exchanged during the engagement shall remain '
     'confidential and shall not be disclosed to any third party without prior written '
     'consent from the respective party.<br><br><strong>7. '
     'Acceptance</strong><br>Commencement of services and/or payment against invoices '
     'shall be considered acceptance of these payment terms and engagement conditions by '
     'the client organisation.'),
    ('Term and Commencement',
     'This Agreement shall commence on the Effective Date and shall continue for the '
     'period specified in the applicable schedules, unless terminated earlier in '
     'accordance with this Agreement. Where subscription or recurring services apply, the '
     'applicable service term shall be governed by Schedule B and any related service '
     'schedule.'),
    ('Assumptions, Dependencies, and Change in Scope',
     'The Client acknowledges that the Services, commercials, delivery sequencing, and '
     'timing assumptions reflected in this Agreement are based on the assumptions and '
     'dependencies described in Schedule C and any other applicable schedule. Material '
     'changes in scope, entity count, transaction volume, systems architecture, '
     'stakeholder availability, third-party vendor involvement, or any other relevant '
     'operating assumption may require commercial and delivery review.'),
    ('Standard of Performance',
     'KGRN shall perform the Services with reasonable skill, care, and diligence '
     'consistent with the nature of the engagement and the professional standards '
     'ordinarily applicable to services of a similar kind.'),
    ('Confidentiality',
     'Each party shall keep confidential all non-public commercial, financial, technical, '
     'operational, and business information received from the other party in connection '
     'with this Agreement and shall not disclose such information to any third party '
     'except as permitted for performance, professional advice, or legal requirement.'),
    ('Intellectual Property and Work Product',
     'Each party shall retain ownership of its pre-existing intellectual property, '
     'materials, methodologies, know-how, tools, templates, and proprietary frameworks. '
     'Subject to payment in full, the Client shall have the right to use the agreed '
     'deliverables provided by KGRN for the Client’s internal business purposes in '
     'connection with the Services.'),
    ('Limitation of Liability',
     'To the maximum extent permitted by applicable law, KGRN’s aggregate liability '
     'arising out of or in connection with this Agreement shall not exceed the total fees '
     'actually paid to KGRN under this Agreement during the twelve months immediately '
     'preceding the event giving rise to the claim.'),
    ('Suspension of Services',
     'KGRN reserves the right to suspend performance of the Services upon reasonable '
     'notice where invoices remain unpaid beyond the applicable due date, the Client fails'
     ' to provide material cooperation, dependencies prevent progress, or continued '
     'performance would place KGRN at material legal, compliance, or operational risk.'),
    ('Termination',
     'Either party may terminate this Agreement for convenience where permitted under the '
     'applicable service model, immediately upon unremedied material breach, or '
     'immediately if the other party becomes insolvent, enters liquidation, or is '
     'otherwise unable to perform its obligations.'),
    ('Governing Law and Jurisdiction',
     'This Agreement shall be governed by and construed in accordance with the laws '
     'applicable in the Dubai International Financial Centre (DIFC), and the courts of the'
     ' DIFC shall have exclusive jurisdiction unless the parties expressly agree otherwise'
     ' in writing.'),
    ('Entire Agreement and Electronic Signature',
     'This Agreement, together with its schedules and appendices, constitutes the entire '
     'agreement between the parties. It may be executed in counterparts, and signatures '
     'delivered electronically or by PDF shall be deemed valid and effective for all '
     'purposes.'),
]

# ── Schedule C: assumptions and dependencies (SE wording, not the proposal's) ─
SE_ASSUMPTIONS = [
    'Timely access to relevant stakeholders, decision-makers, and process owners within '
    "the Client's organisation.",
    'Availability of required business, process, and systems information in a format and '
    'timeframe suitable for engagement purposes.',
    'Clarity on entity scope, transaction scope, and operating model, confirmed within a '
    'reasonable time of engagement commencement.',
    'Timely completion of required approvals, procurement steps, and contracting '
    "formalities on the Client's side.",
    'No material change in the scope, complexity, or dependency profile without a formal '
    'change request and commercial review.',
    "Cooperation from the Client's internal teams — finance, tax, IT, procurement, and "
    'operations — throughout the engagement lifecycle.',
    'Where third-party vendors or system integrators are involved, the Client will '
    'provide reasonable coordination support and access management.',
    "The Client's technical environment and systems are broadly capable of supporting the"
    ' agreed implementation approach. Any material deviation may require additional '
    'scoping and commercial review.',
]

# ── Schedule D: support model (only when a service coded "D" is on the order) ─
SE_SUPPORT_MODEL = [
    ('Service Scope',
     'Recurring support management, monitoring and exception handling, and operational '
     'governance as described in Schedule A.'),
    ('Support Availability',
     'Business hours support (Sunday–Thursday, 09:00–18:00 GST) unless otherwise agreed. '
     'Critical issue escalation available outside standard hours by prior arrangement.'),
    ('Response Targets',
     'Critical issues: within 4 business hours. Standard requests: within 1–2 business '
     'days. Non-urgent queries: within 3 business days.'),
    ('Governance',
     'Periodic operational review meetings (frequency to be agreed). Service reporting on '
     'key metrics, exception trends, and volume activity as agreed.'),
    ('Exclusions',
     'Issues arising from changes made by the Client outside the agreed operating model; '
     'third-party vendor or ASP platform outages; changes in regulatory requirements not '
     'covered under the agreed scope.'),
]

# ── Schedule E: rollout phasing (only when a service coded "E" is present) ────
SE_ROLLOUT_PHASES = [
    ('Phase 1 — Scope & Structure',
     'Confirm entity scope, prioritise entities for rollout, establish governance and '
     'coordination framework.',
     'All entities to be listed and prioritised by end of Phase 1.'),
    ('Phase 2 — Pilot Entity',
     'Implement and onboard the first entity. Validate approach, resolve dependencies, '
     'confirm replicable model.',
     'Pilot entity confirmed at engagement start. Outcomes inform rollout playbook.'),
    ('Phase 3 — Staged Rollout',
     'Onboard remaining entities in agreed batches. Apply and adapt the rollout playbook '
     'as required.',
     'Batch sequence and timing to be agreed at Phase 1 exit.'),
    ('Phase 4 — Stabilise & Govern',
     'Confirm full entity coverage, establish ongoing governance, and transition to '
     'operational model.',
     'Includes final review and handover documentation.'),
]

SE_ROLLOUT_NOTE = (
    'Note: The above phasing is indicative. Actual phase boundaries, timelines, and '
    'entity batching will be confirmed as part of the Phase 1 scope and structure '
    'activity. Any material increase in entity count or complexity during rollout is '
    'subject to commercial review.'
)
